import re
import arrow
from lxml import etree
from bitstring import BitArray
from config.config import Config
from functools import wraps, partial
import inspect
import traceback
import logging
from pubsub import pub
import traceback

class XMLParser:
    AHeader  = 'header'
    AFunchar = 'funchar'
    Abytepos = 'bytepos'
    Abitpos = 'bitpos'
    AValue = 'value'
    AConvert = 'convert'
    AMsg = 'msg'
    ATag = 'tag'
    AStore = 'store'
    AFlag = 'flag'

    def __init__(self):
        if Config.PRODUCT_XML_CHANGED:
            Config.PRODUCT_XML_CHANGED = False
            parser = etree.XMLParser(encoding='utf-8', remove_blank_text=True, remove_comments=True)
            self.tree = etree.parse(Config.PRODUCT_XML, parser=parser)
            Config.PRODUCT_XML_TREE = self.tree
        else:
            self.tree = Config.PRODUCT_XML_TREE

        self.root = self.tree.getroot()
        self.frameheader_length = 2

        self._recv_path = './recv'
        self._send_path = './send'
        self._option = './option'

        self.default_send_frameheader = None
        self.default_recv_frameheader = None
        self.send_checksum_func = None
        self.recv_checksum_func = None

        self.initialize_option()

    def initialize_option(self):
        option_ele = self.root.find(self._option)
        if option_ele is not None:  #选取配置的帧信息
            self.default_send_frameheader = option_ele.get('send_frameheader')
            self.default_recv_frameheader = option_ele.get('recv_frameheader')
            self.send_checksum_func = option_ele.get('send_checksum')
            self.recv_checksum_func = option_ele.get('recv_checksum')
        else:   #使用默认的帧信息
            self.default_send_frameheader = '0xAAAA'
            self.default_recv_frameheader = '0xFFF1'

    def iter_recv(self):
        return self.root.iterfind(self._recv_path)

    def iter_send(self):
        return self.root.iterfind(self._send_path)

    def frameheader_recv(self):
        frameheader_recv_dict = {}
        for recv_item in self.iter_recv():
            header = BitArray('{},{}'.format(recv_item.get(self.AHeader, self.default_recv_frameheader), recv_item.get(self.AFunchar)))
            frameheader_recv_dict[header.bytes] = recv_item

        return frameheader_recv_dict

class BytesBuffer:
    HEADER_SENDER = None
    HEADER_RECVER = None
    def __init__(self):
        self.buffer = bytearray()
        self.frame_list = []

    @classmethod
    def set_header(cls, sender, recver):
        if isinstance(sender, str):
            cls.HEADER_SENDER = BitArray(sender).tobytes()
        elif isinstance(sender, bytes):
            cls.HEADER_SENDER = sender

        if isinstance(recver, str):
            cls.HEADER_RECVER = BitArray(recver).tobytes()
        elif isinstance(recver, bytes):
            cls.HEADER_RECVER = recver

    def extend(self, data:bytes):
        self.buffer.extend(data)

    def firstFrame(self):
        if len(self.frame_list):
            return self.frame_list[0]
        else:
            return b''

    def lastFrame(self):
        if len(self.frame_list):
            return self.frame_list[-1]
        else:
            return b''

    def currentFrame(self, header='recver'):
        if header == 'recver':
            header = self.HEADER_RECVER
        elif header == 'sender':
            header = self.HEADER_SENDER

        frame = b''
        try:
            match_header = re.search(header, self.buffer, re.S)
            if match_header:
                # funchar 1byte: self.buffer[match_header.end()]
                # datalen 1byte
                datalen = self.buffer[match_header.end() + 1]
                #checksum 1byte:
                frame = self.buffer[match_header.start():match_header.end() + 1 + 1 + datalen + 1]

                #校验数据帧长度
                if len(frame) != len(header) + 1 + 1 + datalen + 1:
                    frame = b''
                else:
                    self.frame_list.append(frame)
                    self.buffer = self.buffer.replace(frame, b'', 1)
        except Exception:
            frame = b''

        return bytes(frame)

    def frames(self):
        return self.frame_list

def parse_datetime(value):
    a = arrow.get(value)
    return a.format('YYYY-MM-DD HH:mm:ss')

class DebugClass:
    def __init__(self, cls, debug=True):
        self.debug = debug
        wraps(cls)(self)
        for funname, fun in inspect.getmembers(cls):
            if not funname.startswith('__') and inspect.isfunction(fun):
                fun = self.debugfun(fun)
                setattr(cls, funname, fun)

    def __call__(self, *args, **kwargs):
        return self.__wrapped__(*args, **kwargs)

    def debugfun(self, func=None, *, level=logging.ERROR):
        if func is None:
            return partial(self.debugfun, level=level)

        @wraps(func)
        def wrapper(*args, **kwargs):
            value = None
            if self.debug:
                try:
                    value = func(*args, **kwargs)
                except Exception as e:
                    print(traceback.format_exc())
                    pub.sendMessage(Config.TOPIC_EXCEPTION,  triggered=True)
                    Config.LOGGER.log(level, traceback.format_exc())
            else:
                value = func(*args, **kwargs)

            return value

        return wrapper
