import logging
import os
from datetime import date

class Logger:
    def __init__(self, name:str) -> None:
        os.makedirs("./logs", exist_ok=True)
        
        self.logger = logging.getLogger(name=name)
        self.logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter('| %(asctime)s | %(name)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')        
        
        file_handler = logging.FileHandler(filename=f'./logs/{date.today()}.log') 
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler) 
        
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

    def debug(self, log:str) -> None:
        self.logger.debug(log)
    
    def info(self, log:str) -> None:
        self.logger.info(log)
        
    def warning(self, log:str) -> None:
        self.logger.warning(log)

    def error(self, log:str) -> None:
        self.logger.error(log)        

    def critical(self, log:str) -> None:
        self.logger.critical(log)