import os
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


class Converter:
    def __init__(
            self, 
            input_file: str, 
            max_duration_sec: float = 3.0, 
            max_size_kb: int = 256,             
            img_size_x: int = 512,  
            img_size_y: int = 512
            ):
        self.input_path = Path(input_file)
        self.output_path = self.input_path.with_suffix(".webm")
        self.MAX_DURATION_SEC = max_duration_sec
        self.MAX_SIZE_KB = max_size_kb        
        self.IMG_SIZE_X = img_size_x
        self.IMG_SIZE_Y = img_size_y

    
    def calculate_bitrate(self, file_size_kb: int, duration_sec: float) -> int:        
        return (file_size_kb * 8) // duration_sec


    async def get_video_duration(self) -> float:        
        command = (
            "ffprobe -v error -select_streams v:0 "
            "-show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "
            f"{self.input_path}"
        )
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"ffprobe failed with exit code {process.returncode}. Error: {stderr.decode()}")

        return float(stdout.decode().strip())


    async def encode_video(self, bitrate_kbps: int, speed_factor: float) -> None:        
        # cuda
        command = (
            f"ffmpeg -hwaccel cuda -i {self.input_path} "
            f"-filter:v \"setpts={1 / speed_factor}*PTS,scale=512:512,format=yuv420p\" "
            f"-c:v libvpx-vp9 "
            f"-b:v {bitrate_kbps}k "
            "-pix_fmt yuv420p "
            "-an "
            "-sn "
            "-y "
            "-loglevel warning "
            "-hide_banner "
            "-stats "
            f"{self.output_path}"
        )
        # command = (
        #     f"ffmpeg -i {self.input_path} "
        #     f"-filter:v \"setpts={1 / speed_factor}*PTS,scale=512:512,format=yuv420p\" "
        #     f"-c:v libvpx-vp9 "
        #     f"-b:v {bitrate_kbps}k "
        #     # "-pix_fmt yuva420p "
        #     "-pix_fmt yuv420p "
        #     "-an "
        #     "-sn "
        #     "-y "
        #     "-loglevel warning "
        #     "-hide_banner "
        #     "-stats "
        #     f"{self.output_path}"
        # )

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {process.returncode}. Error: {stderr.decode()}")


    async def get_file_size(self) -> float:        
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor() as pool:
            size = await loop.run_in_executor(pool, os.path.getsize, str(self.output_path))
            
        return size / 1024


    async def convert_video(self) -> None:        
        original_duration_sec = await self.get_video_duration()
        speed_factor = max(1, original_duration_sec / self.MAX_DURATION_SEC)
        bitrate_kbps = self.calculate_bitrate(self.MAX_SIZE_KB, self.MAX_DURATION_SEC)

        tolerance_kb = 25          
        count = 0
        max_attempts = 5
        
        while True:
            await self.encode_video(bitrate_kbps, speed_factor)
            file_size_kb = await self.get_file_size()
            file_size_diff_kb = abs(file_size_kb - self.MAX_SIZE_KB)

            if file_size_diff_kb > 100:
                step_kbps = 150
            elif file_size_diff_kb > 50:
                step_kbps = 100
            elif file_size_diff_kb > 25:
                step_kbps = 50
            else:
                step_kbps = 25

            if count >= max_attempts and file_size_kb <= self.MAX_SIZE_KB:
                print(f"Success! Encoded video size: {file_size_kb:.2f} KB with bitrate: {bitrate_kbps} kbps")
                break

            if file_size_kb <= self.MAX_SIZE_KB - tolerance_kb:
                print(f"File size {file_size_kb:.2f} KB is below the limit. Increasing bitrate.")
                bitrate_kbps += step_kbps
            elif file_size_kb <= self.MAX_SIZE_KB:
                print(f"Success! Encoded video size: {file_size_kb:.2f} KB with bitrate: {bitrate_kbps} kbps")
                break
            else:
                print(f"File size {file_size_kb:.2f} KB exceeds limit. Reducing bitrate.")
                bitrate_kbps -= step_kbps
                # if count > 0: count -= 1

                if bitrate_kbps <= 0:
                    print("Error: Bitrate too low. Cannot meet file size requirement.")
                    break
                
                continue

            count += 1            

