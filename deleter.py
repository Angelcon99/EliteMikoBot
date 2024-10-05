import asyncio
import os
import shutil
import asyncio
import logging


class Deleter:
    _lock = asyncio.Lock()
    
    @staticmethod
    async def _delete_path(path: str) -> None:        
        try:
            if os.path.exists(path):                    
                await asyncio.to_thread(shutil.rmtree, path)
        except Exception as e:
            logging.error(f"Failed to delete {path}: {e}")
    
    @staticmethod
    async def delete_all(img_path: str, sticker_path: str) -> None:          
        async with Deleter._lock: 
            await asyncio.gather(
                Deleter._delete_path(img_path),
                Deleter._delete_path(sticker_path)
            )
        
    @staticmethod
    async def delete_dccon(img_path: str) -> None:
        async with Deleter._lock:
            await Deleter._delete_path(img_path)
        