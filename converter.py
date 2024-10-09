import os
import asyncio
import aiofiles
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

class Converter:
    def __init__(self, 
                 input_folder: str,  
                 out_path: str,
                 frame_durations: list,       
                 has_alpha_channel: bool,          
                 max_duration_ms: int = 3000, 
                 max_size_kb: int = 256,  
                 img_size_x: int = 512, 
                 img_size_y: int = 512):
        self.input_folder = Path(input_folder)
        self.output_path = Path(out_path)
        self.frame_durations = frame_durations    
        self.has_alpha_channel = has_alpha_channel
        self.MAX_DURATION_MS = max_duration_ms     
        self.MAX_SIZE_KB = max_size_kb        
        self.IMG_SIZE_X = img_size_x
        self.IMG_SIZE_Y = img_size_y
        self.timeline = f"{self.input_folder}/timeline.txt"

    def calculate_bitrate(self, file_size_kb: int, duration_sec: float) -> int:
        return (file_size_kb * 8) // duration_sec        

    # 듀레이션 조절
    def adjust_durations(self):
        total_duration = sum(self.frame_durations)
        
        if total_duration > self.MAX_DURATION_MS:
            scale_factor = self.MAX_DURATION_MS / total_duration
            self.frame_durations = [int(duration * scale_factor) for duration in self.frame_durations]

    async def generate_timeline(self):
        self.adjust_durations() 
        async with aiofiles.open(self.timeline, 'w') as f:
            for i, duration in enumerate(self.frame_durations):
                if i == 0: continue
                                    
                filename = f"{i:03}.png" 
                duration_seconds = duration / 1000
                await f.write(f"file '{filename}'\n")
                await f.write(f"duration {duration_seconds}\n")


    async def encode_video(self, bitrate_kbps: int) -> None:                       
        await self.generate_timeline()

        if self.has_alpha_channel:
            format = "yuva420p"
            pix_fmt = "yuva420p"
        else:
            format = "yuv420p"
            pix_fmt = "yuv420p"
        # cuda
        # command = (
        #     f"ffmpeg -hwaccel cuda -f concat -safe 0 -i {self.timeline} "
        #     f"-filter:v \"scale={self.IMG_SIZE_X}:{self.IMG_SIZE_Y},format=yuv420p\" "
        #     f"-c:v libvpx-vp9 "
        #     f"-b:v {bitrate_kbps}k "
        #     "-pix_fmt yuv420p "
        #     "-an "
        #     "-sn "
        #     "-y "
        #     "-loglevel warning "
        #     "-hide_banner "
        #     "-stats "
        #     f"{self.output_path}"
        # )
        command = (
            f"ffmpeg -f concat -safe 0 -i {self.timeline} "
            f"-vf scale={self.IMG_SIZE_X}:{self.IMG_SIZE_Y},format={format} "
            f"-c:v libvpx-vp9 "
            f"-b:v {bitrate_kbps}k "
            f"-pix_fmt {pix_fmt} "
            "-an "
            "-sn "
            "-y "
            "-loglevel warning "
            "-hide_banner "
            "-stats "
            f"{self.output_path}"
        )
        
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
        total_duration_sec = sum(self.frame_durations) / 1000.0
                
        bitrate_kbps = self.calculate_bitrate(self.MAX_SIZE_KB, total_duration_sec)

        tolerance_kb = 25
        count = 0
        max_attempts = 5

        while True:
            await self.encode_video(bitrate_kbps)  
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

                if bitrate_kbps <= 0:
                    print("Error: Bitrate too low. Cannot meet file size requirement.")
                    break

                continue

            count += 1
