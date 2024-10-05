import asyncio
from typing import Any, Dict
import aiohttp
import os
import glob
from logger import Logger
from dccon_data import DcconData
from deleter import Deleter


class Dccon():
    def __init__(self):        
        self.logger = Logger(name="Dccon_Log")


    async def fetch_dccon(self, dccon_id: int, path: str) -> DcconData:
        try:
            async with aiohttp.ClientSession() as session:                
                async with session.post(
                    url="https://dccon.dcinside.com/index/package_detail",
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest"
                        },
                    data={"package_idx": dccon_id},
                ) as resp:
                    dccon_meta = await resp.json(content_type="text/html")                                            
                                
                max_try = 3            
                for _ in range(1, max_try):
                    data = await self.get_dccon(dic=dccon_meta, dccon_id=dccon_id, path=path)                     
                    is_success, err = await self.check_dccon(path=path)                
                    if is_success:                
                        break
                    else:
                        data['err'] = err 
                        Deleter.delete_dccon(img_path=path)                                        
                
                dccon_data = DcconData(**data)
                return dccon_data
            
        except Exception as e:
            self.logger.error(f"{dccon_id} 'fetch_dccon' 메서드 실패: {e}")             
            raise


    async def get_dccon(self, dic: Dict[str, Any], dccon_id: int, path: str) -> Dict[str, Any]:       
        try:
            os.makedirs(path, exist_ok=True)

            dccon_data = {}                                                 
            dccon_data['title'] = dic["info"]["title"]
            dccon_data['path'] = path
            dccon_data['id'] = dccon_id
            dccon_data['count'] = 0   
            dccon_data['ext'] = {}         
            num = 1
            async with aiohttp.ClientSession() as session:
                tasks = []
                for data in dic['detail']:
                    url = f"https://dcimg5.dcinside.com/dccon.php?no={data['path']}"
                    tasks.append(self.download_dccon(session, url, path, num, data['ext']))                    
                    dccon_data['count'] += 1
                    dccon_data['ext'][num] = data['ext']
                    num += 1
                
                # 모든 작업을 동시에 실행
                await asyncio.gather(*tasks)                        
            return dccon_data
        except Exception as e:
            self.logger.error(f"{dccon_id} 'get_img' 메서드 실패: {e}")
            raise


    async def download_dccon(self, session: aiohttp.ClientSession, url: str, save_path: str, num: int, ext: str) -> None:
        try:
            headers = {"referer": "https://dccon.dcinside.com/"}
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    with open(f"{save_path}/{num}.{ext}", "wb") as f:
                        f.write(await response.read())
                else:
                    self.logger.error(f"이미지 다운로드 실패: {url}. 상태 코드: {response.status}")
        except Exception as e:
            self.logger.error(f"이미지 다운로드 중 오류 발생: {url}: {e}")

    
    async def check_dccon(self, path: str) -> tuple[bool, str]:
        imgs = glob.glob(os.path.join(path, '*'))
        
        for img in imgs:                        
            img_size = os.path.getsize(img)
            if img_size == 0:
                return (False, "dccon download failed")
            elif  img_size <= 1024:
                return (False, "wrong dccon id")
            
        return (True, None)