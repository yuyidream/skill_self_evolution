import sys,os,subprocess as sp
os.environ['DB_PASSWORD']='local_root_123'
import sys
sys.path.insert(0, r'E:/projects/housekeeping_ai_match/backend/scripts/wx_match')
from processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig
from unittest.mock import MagicMock
s=MagicMock()
s.resume_thumb_bboxes=[[100,200,300,400]]
s.original_resolution=MagicMock(width=720,height=1600)
c=MagicMock();c.click_coords=[200,300]
s.click_context=c
cfg=NicknameOcrConfig()
try:
    _resume_thumb_bindings_and_orphans(screenshot=s,blocks=[],classes=[],claimed_indices=set(),nicknames=(),config=cfg,original_width=720,image_size=(720,1600))
    print('NO ERROR')
except NameError as e:
    print('NameError:',e)
except Exception as e:
    print(type(e).__name__,':',e)
