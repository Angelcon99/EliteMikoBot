from PIL import Image
import os
from typing import Any, Dict
from waifu2x_ncnn_py import Waifu2x
import cv2
import numpy as np
from dccon_data import DcconData
from logger import Logger
from converter import Converter
import asyncio
import concurrent.futures
import aiofiles
from concurrent.futures import ThreadPoolExecutor
from moviepy.editor import VideoFileClip, ImageSequenceClip


class Upscaler():
    def __init__(self, dccon_data: DcconData, sticker_path: str):        
        self.logger = Logger(name="Upscale_Log")        
        self.dccon_id = dccon_data.id    
        self.dccon_count = dccon_data.count
        self.dccon_ext = dccon_data.ext
        self.dccon_path = dccon_data.path   
        self.sticker_save_path = sticker_path        
        self.MAX_IMG_SIZE_KB = 512     
        self.IMG_SIZE_X = 512
        self.IMG_SIZE_Y = 512
        self.waifu2x = Waifu2x(gpuid=0, scale=2, noise=3)   
    
    async def upscale(self) -> None:
        try:
            os.makedirs(self.sticker_save_path, exist_ok=True)
            
            for i in range(1, self.dccon_count + 1):
                await self.check_and_rename_image(file_path=f"{self.dccon_path}/{i}.{self.dccon_ext[i]}", num=i)
                
                if self.dccon_ext[i] == "png":
                    await self.waifu2x_img(num=i)
                else:
                    new_path, frame_durations = await self.divide_gif(num=i, id=self.dccon_id)
                    await self.waifu2x_file(path=new_path)
                    await self.generate_gif(path=new_path, num=i, frame_durations=frame_durations)
                    await self.generate_webm_from_gif(path=self.dccon_path, num=i, frame_duration=frame_durations)                                                        
        
        except Exception as e:
            self.logger.error(f"Upscale 작업 중 오류 발생: {e}")            


    # 디시에서 이미지 확장자를 잘못 넘겨주는 경우 존재
    async def check_and_rename_image(self, file_path, num) -> None:
        try:
            loop = asyncio.get_running_loop()
                        
            def open_image(file_path):
                with Image.open(file_path) as img:
                    return img
                        
            img = await loop.run_in_executor(None, open_image, file_path)
            
            actual_format = img.format.lower()
            file_name, file_extension = os.path.splitext(file_path)
            file_extension = file_extension[1:].lower()
            
            if file_extension != actual_format:
                new_file_path = f"{file_name}.{actual_format}"
                                
                def rename_file(file_path, new_file_path):
                    os.rename(file_path, new_file_path)
                                
                retry_attempts = 3
                for _ in range(retry_attempts):
                    try:
                        await loop.run_in_executor(None, rename_file, file_path, new_file_path)
                        self.dccon_ext[num] = actual_format                        
                        break
                    except OSError as e:
                        pass                            
        
        except Exception as e:
            print(f"check_and_rename_image 작업 중 오류 발생: {e}")

        
    async def waifu2x_process(self, image: np.ndarray) -> np.ndarray:
        """비동기로 이미지를 waifu2x로 처리하고 알파 채널이 있을 경우 보존"""
        loop = asyncio.get_running_loop()

        # 알파 채널 여부 확인
        if image.shape[2] == 4:
            # 알파 채널 추출
            alpha_channel = image[:, :, 3]

            # waifu2x 처리
            image = await loop.run_in_executor(None, self.waifu2x.process_cv2, image)

            # 이미지 크기 얻기
            image_height, image_width = image.shape[:2]

            # 알파 채널을 이미지 크기와 동일하게 리사이즈 (알파 채널이 이미지 크기와 동일하게 되어야 함)
            resize_alpha_channel = await loop.run_in_executor(
                None, cv2.resize, alpha_channel, (image_width, image_height), cv2.INTER_LINEAR
            )

            # BGR -> BGRA 변환 후 알파 채널 복원
            image = await loop.run_in_executor(None, cv2.cvtColor, image, cv2.COLOR_BGR2BGRA)
            image[:, :, 3] = resize_alpha_channel  # 알파 채널 할당 (크기가 맞아야 함)
        else:
            # waifu2x 처리
            image = await loop.run_in_executor(None, self.waifu2x.process_cv2, image)
        
        return image



    async def waifu2x_img(self, num: int) -> None:        
        try:
            loop = asyncio.get_running_loop()
            
            image = await loop.run_in_executor(
                None, lambda: cv2.imdecode(np.fromfile(f"{self.dccon_path}/{num}.png", dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            )
            
            image = await self.waifu2x_process(image)
            
            image = await loop.run_in_executor(None, cv2.resize, image, (self.IMG_SIZE_X, self.IMG_SIZE_Y))
            await loop.run_in_executor(None, lambda: cv2.imencode(".png", image)[1].tofile(f"{self.sticker_save_path}/{num}.png"))
            
            await self.resize_img(path=self.sticker_save_path, num=num)

        except Exception as e:
            self.logger.error(f"waifu2x_img 작업 중 오류 발생: {e}")


    async def resize_img(self, path: str, num: int) -> None:        
        img_path = f"{path}/{num}.png"        
        img = Image.open(img_path)
        img_size = os.path.getsize(img_path) / 1024   # Kb 단위로 변환
        quality = 98
        while img_size > self.MAX_IMG_SIZE_KB:            
            # 이미지 압축                      
            img.save(img_path, quality=quality)
            img_size = os.path.getsize(img_path) / 1024
            quality -= 5                       


    async def divide_gif(self, num: int, id: int) -> tuple:               
        new_path = f"{self.dccon_path}/{id}_{num}"
        if not os.path.exists(new_path):
                    os.makedirs(new_path)

        gif_path = f"{self.dccon_path}/{num}.gif"
        gif_image = Image.open(gif_path)                

        frame_durations = []

        for frame_num in range(gif_image.n_frames):
            gif_image.seek(frame_num)     
            
            duration = gif_image.info.get('duration', 0)
            frame_durations.append(duration)
            
            png_image = gif_image.convert('P', palette=Image.ADAPTIVE)
            # png_image = gif_image.convert('RGBA')
            png_image.save(f'{new_path}/{frame_num:03d}.png')            
                
        return new_path, frame_durations


    async def waifu2x_file(self, path: str) -> None:        
        i = 0
        loop = asyncio.get_running_loop()

        while True:
            file_path = f"{path}/{i:03d}.png"
            try:                
                async with aiofiles.open(file_path, 'rb') as f:
                    data = await f.read()
                
                data_np = np.frombuffer(data, dtype=np.uint8)

                with concurrent.futures.ThreadPoolExecutor() as pool:                    
                    image = await loop.run_in_executor(pool, cv2.imdecode, data_np, cv2.IMREAD_UNCHANGED)
                    
                    image = await self.waifu2x_process(image)
                    
                    # image = await loop.run_in_executor(pool, cv2.resize, image, (208, 208))
                    
                    _, encoded_image = await loop.run_in_executor(pool, cv2.imencode, '.png', image)
                    # if not success:
                    #     self.logger.error(f"waifu2x_file cv2.imencode is fail")

                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(encoded_image.tobytes())

                i += 1
            except FileNotFoundError:
                break
            except Exception as e:
                pass


    async def generate_gif(self, path: str, num: int, frame_durations: list) -> None:    
        loop = asyncio.get_running_loop()
        
        try:                        
            with ThreadPoolExecutor() as pool:
                img_list = await loop.run_in_executor(pool, lambda: os.listdir(path))
                images = []
                for img in img_list:
                    img_path = os.path.join(path, img)
                    # image = await loop.run_in_executor(pool, lambda: Image.open(img_path).convert("RGBA"))
                    image = await loop.run_in_executor(pool, lambda: Image.open(img_path))
                    images.append(image)
                
                gif_path = os.path.join(self.sticker_save_path, f"{num}.gif")
                                
                await loop.run_in_executor(pool, lambda: images[0].save(
                    gif_path, 
                    save_all=True, 
                    append_images=images[1:], 
                    loop=0, 
                    duration=frame_durations,
                    optimize=True,
                    disposal=2              
                ))
                
        except Exception as e:
            self.logger.error(f"generate_gif 중 오류 발생: {e}")


    async def generate_webm_from_gif(self, path:str, num:int, frame_duration: list) -> None:     
        try:                                                    
            converter = Converter(input_file=f"{self.sticker_save_path}/{num}.gif")
            await converter.convert_video()
        except Exception as e:
            self.logger.error(f"generate_webm_from_gif 중 오류 발생: {e}")   
   

    
        
