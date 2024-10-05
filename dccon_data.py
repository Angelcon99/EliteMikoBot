from dataclasses import dataclass

@dataclass
class DcconData:                
    id: int   # dccon_id
    title: str
    path: str
    count: int
    ext: dict[int, str]   # [img_num, img_ext]
    err: str = None