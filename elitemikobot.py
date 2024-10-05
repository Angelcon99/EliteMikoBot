from collections import defaultdict
import random
import string
from telegram import Update, Bot, InputSticker
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,    
    ConversationHandler,
    MessageHandler,
    filters
)
from dccon import Dccon
from dccon_data import DcconData
from upscaler import Upscaler
from logger import Logger
from deleter import Deleter
import os
import shutil
import asyncio
from enum import Enum


class BotConfig:
    IMG_PATH = "./img"
    STICKER_IMG_PATH = "./sticker"
    STICKER_TAG = "_by_EliteMiko_bot"  

    @classmethod
    def init_dir(cls):        
        if os.path.exists(cls.IMG_PATH):
            shutil.rmtree(cls.IMG_PATH)  
        if os.path.exists(cls.STICKER_IMG_PATH):
            shutil.rmtree(cls.STICKER_IMG_PATH)  
                
        os.makedirs(cls.IMG_PATH, exist_ok=True)
        os.makedirs(cls.STICKER_IMG_PATH, exist_ok=True)

    with open("./token.txt") as f:
        value = f.read().strip()
        BOT_TOKEN = value if value else None

    with open("./developer.txt") as f:
        lines = [line.strip() for line in f]        
        DEVELOPER_ID = int(lines[0]) if len(lines) > 0 and lines[0] else None
        DEVELOPER_NAME = lines[1] if len(lines) > 1 and lines[1] else None 

    # 스티커 생성 동시 작업 수 제한
    task_semaphore = asyncio.Semaphore(3)
    # 사용자별로 세마포어와 작업중인 디시콘 아이디 관리
    user_semaphore = defaultdict(lambda: {'semaphore': asyncio.Semaphore(1), 'request_id': None})
    # 작업중인 목록
    sticker_tasks = {}


class HandlerState(Enum):
    ASK_CONFIRMATION = 0    
    PROCESSING = 1


class EliteMikoBot:
    def __init__(self, token) -> None:
        self.logger = Logger(name="EliteMikoBot_Log") 
        BotConfig.init_dir()              
        self.check_config()
        self.bot = Bot(token=token)
        self.application = Application.builder().token(token).write_timeout(30).read_timeout(30).build()                        
        self._setup_handlers()                                        


    def check_config(self) -> None:      
        missing_configs = []
        if BotConfig.BOT_TOKEN is None:
            missing_configs.append("BOT_TOKEN")
        if BotConfig.DEVELOPER_ID is None:
            missing_configs.append("DEVELOPER_ID")
        if BotConfig.DEVELOPER_NAME is None:
            missing_configs.append("DEVELOPER_NAME")

        if len(missing_configs) > 0:
            self.logger.error(f"Missing config: {missing_configs}")
            exit(1)


    def _setup_handlers(self) -> None:        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('cancel', self._cancel)],
            states={
                HandlerState.ASK_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._confirm_cancel)]                
                },
            fallbacks=[],
            conversation_timeout=15
        )
        self.application.add_handler(conv_handler)    
        self.application.add_handler(CommandHandler("start", self._start))
        self.application.add_handler(CommandHandler("create", self._create))
        self.application.add_handler(CommandHandler("help", self._help))
        self.application.add_handler(CommandHandler("cancel", self._cancel))
        self.application.add_handler(CommandHandler("stop", self._stop))

    def run(self) -> None:
        self.logger.info("Start EliteMikoBot")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.message.from_user
        self.logger.info(f"{user.name}({user.id}) requested '/start'")
        await update.message.reply_text(
            " - Elite Miko Bot -\n\n"            
            "디시콘으로 텔레그램 스티커를 만들어주는 봇입니다.\n"
            "디시콘의 해상도를 인공지능 모델로 2배 높여서 스티커를 생성합니다. \n"
            "디시콘의 해상도가 높을수록 스티커 해상도가 높습니다. \n\n"
            "- 움짤이 많을수록 오랜 시간이 소요됩니다. \n"
            "- 움짤 최대 재생 시간이 3초이기 때문에 긴 움짤은 재생 속도가 빨라집니다. \n"
            "- 2D 사진 인공지능 모델을 사용하기 때문에 3D 사진은 이상하게 나올 수 있습니다. \n"
            "- 자세한 내용은 /help 를 통해 확인할 수 있습니다. \n\n"
            "니에.."
        )   


    async def _help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:       
        await update.message.reply_text(
            "- 스티커 등록 방법 - \n\n"
            "/create [dccon id] 를 통해 스티커를 생성할 수 있습니다. \n"
            "ex) /create 138771 \n\n"
            "디시콘 링크의 # 뒤의 숫자가 dccon id 입니다. \n"
            "ex) dccon.dcinside.com/#138771 \n\n"
            "스티커는 동시에 1개만 만들 수 있으며, 봇이 동시에 만들 수 있는 스티커 수는 제한되어 있습니다. \n"            
            "/cancel [dccon id] 를 통해 작업중인 스티커를 취소할 수 있습니다. \n"
            "작업을 거절당하면 잠시후에 다시 시도해주세요. "
        )

           
    async def _create(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.message.from_user            
        dccon_id, option_c = self.parse_command(update.message.text)

        if dccon_id is not None:
            self.logger.info(f"{user.name}({user.id}) requested '/create {dccon_id}'")
            await update.message.reply_text("좃또맛뛔니에")
            
            BotConfig.sticker_tasks[dccon_id] = asyncio.create_task(self._process_sticker_request(update, context, dccon_id, option_c))
        else:
            await update.message.reply_text("/create [dccon id] 형태로 입력해줘")


    def parse_command(self, user_text: str) -> tuple:
        dccon_id = user_text[-6:].strip()   # dccon id = 5~6 letters
        option_c = "-c" in user_text
        return (dccon_id if dccon_id.isdigit() else None, option_c)


    async def _process_sticker_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, dccon_id: str, option_c: bool) -> None:
        user = update.message.from_user
        user_semaphore = BotConfig.user_semaphore[user.id]['semaphore']
        
        if BotConfig.task_semaphore.locked():
            self.logger.warning(f"{dccon_id} requested by {user.name}({user.id}) rejected: semaphore full")
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"{user.id}번 디씨콘 작업을 거절당했다 니에... (동시 작업 수 초과)"
                )
            return

        if user_semaphore.locked():        
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"이미 {BotConfig.user_semaphore[user.id]['request_id']}번 디씨콘을 작업중이니에..."
                )
            return
                
        for user_task in BotConfig.user_semaphore.values():        
            if dccon_id == user_task['request_id']:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"다른 사용자가 {BotConfig.user_semaphore[user.id]['request_id']}번 디씨콘을 작업중이니에... 조금만 기다려줘"
                    )
                return
        
        BotConfig.user_semaphore[user.id]['request_id'] = dccon_id

        #  task_semaphore, user_semaphore[user.id]['semaphore'] 획득
        async with BotConfig.task_semaphore, user_semaphore:                    
            try:
                sticker_name_set = await self._img_processing(update=update, dccon_id=dccon_id, option_c=option_c)
                
                if sticker_name_set is not None:
                    await self._send_sticker_links(update, context, sticker_name_set)             
                    self.logger.info(f"{dccon_id} requested by {update.message.from_user.name}({update.message.from_user.id}) succeeded")                       
                else:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id, 
                        text=f"{dccon_id}번 디씨콘 작업을 실패했다니에..."
                        )
                    self.logger.warning(f"{dccon_id} requested by {update.message.from_user.name}({update.message.from_user.id}) failed")                       
                    return                
            except Exception as e:
                self.logger.error(f"_process_sticker_request fail(dccon_id={dccon_id}) : {e}")
            finally:
                BotConfig.user_semaphore[user.id]['request_id'] = None
                del BotConfig.sticker_tasks[dccon_id]
        

    async def _img_processing(self, update: Update, dccon_id: int, option_c: bool) -> list:
        try:
            # await Deleter.delete_all(
            #         img_path = f"{BotConfig.IMG_PATH}/{dccon_id}",
            #         sticker_path = f"{BotConfig.STICKER_IMG_PATH}/{dccon_id}" 
            #     )             
            dccon = Dccon()
            dccon_data = await dccon.fetch_dccon(dccon_id=dccon_id, path=f"{BotConfig.IMG_PATH}/{dccon_id}")

            if dccon_data.err:
                self.logger.error(f"_img_processing(dccon) fail(dccon_id={dccon_id}) : {dccon_data.err}")
                return None
            
            upscale = Upscaler(dccon_data=dccon_data, sticker_path=f"{BotConfig.STICKER_IMG_PATH}/{dccon_id}")        
            await upscale.upscale()
        
            sticker_name_set = await self._create_sticker_set(dccon_data=dccon_data, option_c=option_c)                                     
            return sticker_name_set            
                                                                                   
        except Exception as e:
            self.logger.error(f"_img_processing fail(dccon_id={dccon_id}) : {e}")
            return None        
        
        finally:
            await Deleter.delete_all(
                img_path = f"{BotConfig.IMG_PATH}/{dccon_id}",
                sticker_path = f"{BotConfig.STICKER_IMG_PATH}/{dccon_id}" 
            )


    async def _create_sticker_set(self, dccon_data: DcconData, option_c: bool) -> list:
        try:
            sticker_name_set = [self.make_sticker_name(dccon_data.id)]
            sticker_set, sticker_set2 = await self._prepare_stickers(dccon_data, option_c)

            await self._create_new_sticker_set(dccon_data, sticker_name_set[0], sticker_set)

            if sticker_set2:
                if option_c:
                    sticker_name_set.append(self.make_sticker_name(dccon_data.id))
                    await self._create_new_sticker_set(dccon_data, sticker_name_set[1], sticker_set2)
                else:
                    await self._add_stickers_to_set(sticker_name_set[0], sticker_set2)
            return sticker_name_set
        except Exception as e:
            self.logger.error(f"_create_sticker_set fail : {e}")


    # db 연결하면 수정
    def make_sticker_name(self, id: int) -> str:        
        return f"{''.join(random.sample(string.ascii_lowercase + string.ascii_uppercase, 5))}{id}{BotConfig.STICKER_TAG}"


    async def _create_new_sticker_set(self, dccon_data: DcconData, name: str, stickers: list):
        try:
            await self.bot.create_new_sticker_set(
                user_id=BotConfig.DEVELOPER_ID,
                name=name,
                title=f"{dccon_data.title} @EliteMiko_bot",
                stickers=stickers,
                read_timeout=30,
                write_timeout=30
            )
        except Exception as e:
            self.logger.error(f"_create_new_sticker_set fail : {e}")


    async def _add_stickers_to_set(self, name: str, stickers: list):
        try:
            for sticker in stickers:
                await self.bot.add_sticker_to_set(
                    user_id=BotConfig.DEVELOPER_ID,
                    name=name,
                    sticker=sticker,
                    read_timeout=30,
                    write_timeout=30
                )
        except Exception as e:
                self.logger.error(f"_add_stickers_to_set fail : {e}")


    async def _send_sticker_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE, sticker_name_set: list):
        try:
            for name in sticker_name_set:
                # await asyncio.sleep(20)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=f"https://t.me/addstickers/{name}", 
                    read_timeout=30, 
                    write_timeout=30
                    )
        except Exception as e:
            self.logger.error(f"_send_sticker_links fail: {e}")


    async def _prepare_stickers(self, dccon_data: DcconData, option_c: bool) -> tuple:    
        path = f"{BotConfig.STICKER_IMG_PATH}/{dccon_data.id}"
        sticker_set = []
        sticker_set2 = []        

        for i in range(1, dccon_data.count + 1):
            ext = "png" if dccon_data.ext[i] == "png" else "webm"
            format = "static" if ext == "png" else "video"
            
            try:
                sticker = InputSticker(
                    sticker=open(f"{path}/{i}.{ext}", "rb"), 
                    emoji_list=["\U0001F338"], 
                    format=format
                    )
                (sticker_set if i <= 50 else sticker_set2).append(sticker)
            except FileNotFoundError as e:                
                pass    
        return sticker_set, sticker_set2


    async def _cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.message.from_user
        dccon_id, _ = self.parse_command(update.message.text)
        user_request_id = BotConfig.user_semaphore[user.id]['request_id']

        if dccon_id is None:
            await update.message.reply_text(f"/cancel 번호 형태로 입력해줘")
            return ConversationHandler.END
        elif not dccon_id and dccon_id != user_request_id:
            await update.message.reply_text(f"{dccon_id} 작업이 존재하지 않아")
            return ConversationHandler.END            
        else:
            await update.message.reply_text(f"{dccon_id} 작업을 정말 취소할꺼야? [y/n]")
            return HandlerState.ASK_CONFIRMATION            


    async def _confirm_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:                        
        user_answer = update.message.text.lower()
        if user_answer == 'y':            
            await self._cancel_sticker_request(update, context)
        return ConversationHandler.END


    async def _cancel_sticker_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:        
        user = update.message.from_user
        user_request_id = await self._delete_semaphore(user_id=user.id)        
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"{user_request_id}번 디씨콘 작업을 취소했다니에..."
            )

    
    async def _delete_semaphore(self, user_id: int) -> int:
        user_data = BotConfig.user_semaphore.get(user_id) 
        request_id = user_data['request_id']       

        if user_data:                        
            if user_data['semaphore'].locked():
                user_data['semaphore'].release()  

            # 작업이 있는 경우 해당 dccon_id 작업 취소
            if request_id in BotConfig.sticker_tasks:                
                task = BotConfig.sticker_tasks.pop(request_id)
                if task and not task.done():
                    task.cancel()

            user_data['request_id'] = None

        await Deleter.delete_all(
            img_path=f"{BotConfig.IMG_PATH}/{request_id}", 
            sticker_path=f"{BotConfig.STICKER_IMG_PATH}/{request_id}"
            )
        
        return request_id


    # Only available to developer
    async def _stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.message.from_user
        if user.id == BotConfig.DEVELOPER_ID and user.name == BotConfig.DEVELOPER_NAME:            
            for user_id in BotConfig.user_semaphore.keys():
                request_id = await self._delete_semaphore(user_id) 
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=f"{user_id}의 {request_id}작업이 취소 되었습니다."
                    )
                
            await update.message.reply_text("봇을 종료한다 니에")                                  
            self.logger.info("----- Stop EliteMikoBot -----")                                 
            asyncio.get_event_loop().stop()                            
                


if __name__ == "__main__":
    bot = EliteMikoBot(BotConfig.BOT_TOKEN)
    bot.run()    
