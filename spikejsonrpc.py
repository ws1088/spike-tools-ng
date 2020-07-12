#!/usr/bin/env python
import serial
import base64
import os
import sys
import argparse
from tqdm import tqdm
import time
import json
import random
import string
import logging
from datetime import datetime


class RPC:
    letters = string.ascii_letters + string.digits + '_'

    def __init__(self, tty='/dev/ttyACM0'):
        for i in range(1, 6):
            try:
                self.ser = serial.Serial(tty, 115200)
                # self.ser = serial.Serial(tty, 9600)
                break
            except:
                print(f'Retrying ({i})...')
        self.recv_buf = bytearray()

    @staticmethod
    def random_id(length=4):
        return ''.join(random.choice(RPC.letters) for _ in range(length))

    def recv_message(self, timeout=1, console_out=False):
        start_time = time.time()
        elapsed = 0
        while True:
            pos = self.recv_buf.find(b'\x0d')
            # if len(self.recv_buf) > 0:
            #     logging.debug(f'XXX: {self.recv_buf}')
            if pos >= 0:
                result = self.recv_buf[:pos]
                self.recv_buf = self.recv_buf[pos + 1:]
                data = result.decode('utf-8')

                idx = data.find('{')
                if idx != -1:
                    data = data[idx:]
                try:
                    res = json.loads(data)
                    self.process_json(res)
                    return res
                except json.JSONDecodeError:
                    if len(data):
                        logging.debug("Cannot parse JSON: %s" % data)
                        if console_out:
                            print(data)
                        pass
                    pass
            c = self.ser.inWaiting()
            if c == 0 and elapsed >= timeout:
                break
            self.ser.timeout = timeout
            new_data = self.ser.read(c if c else 1)
            if len(new_data):
                # print('aaa:', new_data)
                self.recv_buf = self.recv_buf + new_data
                pass

            elapsed = time.time() - start_time
        return None

    def send_message_0(self, msg):
        msg_string = json.dumps(msg)
        logging.debug('sending: %s' % msg_string)
        # self.ser.write(msg_string.encode('utf-8')+b'\x0D')
        # self.ser.flush()
        self.ser.write(msg_string.encode('utf-8'))
        self.ser.write(b'\x0D')
        # self.ser.flush()

    def send_message(self, name, params={}, timeout=1):
        while True:
            if not self.recv_message(timeout=0):
                break

        id = RPC.random_id()
        msg = {'i': id, 'm': name, 'p': params}
        self.send_message_0(msg)

        return self.recv_response(id, timeout=1)

    def recv_response(self, id, timeout=1, console_out=False):
        start_time = time.time()
        elapsed = 0
        while True:
            if elapsed >= timeout:
                logging.debug(f'Timeout while waiting for response for id: {id}')
                return
            m = self.recv_message(timeout=1, console_out=console_out)
            if m is None:
                continue
            if 'i' in m and m['i'] == id:
                logging.debug(f'getting: {m} for {id}')
                if 'e' in m:
                    error = json.loads(base64.b64decode(m['e']).decode('utf-8'))
                    raise ConnectionError(error)
                return m['r']
            else:
                # logging.debug(f'getting: {m}')
                pass

            # logging.debug(f'While waiting for response: {m}')
            elapsed = time.time() - start_time

    # Program Methods
    def program_execute(self, n):
        # self.get_firmware_info()
        # self.send_message('trigger_current_state')
        # time.sleep(0.1)
        self.send_message('program_modechange', {'mode': 'download'})
        # time.sleep(0.1)

        res = self.send_message('program_execute', {'slotid': n})
        # time.sleep(0.5)

        self.recv_response('', timeout=120, console_out=True)

        return res

    def program_terminate(self):
        return self.send_message('program_terminate')

    def get_storage_information(self):
        time.sleep(1)
        self.send_message('trigger_current_state')
        return self.send_message('get_storage_status', timeout=0)

    def start_write_program(self, name, size, slot, created, modified):
        short_name = name.split(os.sep)
        meta = {'created': created, 'modified': modified, 'name': name, 'type': 'python',
                'project_id': RPC.random_id(12)}
        res = self.send_message('start_write_program', {'slotid': slot, 'size': size, 'meta': meta})
        return res

    def write_package(self, data, transferid):
        return self.send_message('write_package',
                                 {'data': str(base64.b64encode(data), 'utf-8'), 'transferid': transferid})

    def move_project(self, from_slot, to_slot):
        return self.send_message('move_project', {'old_slotid': from_slot, 'new_slotid': to_slot})

    def remove_project(self, from_slot):
        return self.send_message('remove_project', {'slotid': from_slot})

    # Light Methods
    def display_set_pixel(self, x, y, brightness=9):
        return self.send_message('scratch.display_set_pixel', {'x': x, 'y': y, 'brightness': brightness})

    def display_clear(self):
        return self.send_message('scratch.display_clear')

    def display_image(self, image):
        return self.send_message('scratch.display_image', {'image': image})

    def display_image_for(self, image, duration_ms):
        return self.send_message('scratch.display_image_for', {'image': image, 'duration': duration_ms})

    def display_text(self, text):
        return self.send_message('scratch.display_text', {'text': text})

    # Hub Methods
    def get_firmware_info(self):
        return self.send_message('get_firmware_info')

    def process_json(self, res):
        if 'm' in res.keys():
            if res['m'] == 0 or res['m'] == 2:
                return
            # print('JSON:', res)
            if res['m'] == 'runtime_error' or res['m'] == 'user_program_error':
                error = RPC.decode(res['p'][3])
                print('Error: {}'.format(error), file=sys.stderr)
                raise SystemExit
                return
            if res['m'] == "userProgram.print":
                data = res['p']['value']
                id = res['i']
                print(RPC.decode(data), end='')
                msg = {'i': id, 'r': None}
                self.send_message_0(msg)
                return
            logging.debug(res)
        elif 'e' in res.keys():
            logging.debug(f"Error: {RPC.decode(res['e'])}")
        else:
            # print('what is that?', res)
            pass

    @staticmethod
    def decode(data):
        return base64.b64decode(data).decode('utf-8')


if __name__ == "__main__":
    def handle_list():
        info = rpc.get_storage_information()
        if info is None:
            return
        storage = info['storage']
        slots = info['slots']
        print("%2s %-40s %6s %6s %20s" % ("#", "Name", "Size", "Id", "Last Modified"))
        for i in range(20):
            if str(i) in slots:
                sl = slots[str(i)]
                modified = datetime.utcfromtimestamp(sl['modified'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                print("%2s %-40s %5db %6s %20s" % (i, sl['name'], sl['size'], sl['id'], modified))
        print(("%s/%s%s Free" % (storage['free'], storage['total'], storage['unit'])).rjust(78))

    def handle_fwinfo():
        info = rpc.get_firmware_info()
        fw = '.'.join(str(x) for x in info['version'])
        rt = '.'.join(str(x) for x in info['runtime'])
        print("Firmware version: %s; Runtime version: %s" % (fw, rt))

    def handle_reboot():
        rpc.ser.write(b'\r\x03\x03')
        # rpc.ser.write(b'\x0D')
        time.sleep(0.1)
        rpc.ser.write(b'\r\x04');
        print('Please waiting while hub is reconnecting...')
        # todo: Faster exit, maybe kill the serial connections?

    def handle_upload():
        with open(args.file, "rb") as f:
            size = os.path.getsize(args.file)
            name = args.name if args.name else args.file
            now = int(time.time() * 1000)
            start = rpc.start_write_program(name, size, args.to_slot, now, now)
            bs = start['blocksize']
            id = start['transferid']
            with tqdm(total=size, unit='B', unit_scale=True) as pbar:
                b = f.read(bs)
                while b:
                    rpc.write_package(b, id)
                    pbar.update(len(b))
                    b = f.read(bs)
            if args.start:
                rpc.program_execute(args.to_slot)

    parser = argparse.ArgumentParser(description='Tools for Spike Hub RPC protocol')
    parser.add_argument('-t', '--tty', help='Spike Hub device path', default='/dev/ttyACM0')
    parser.add_argument('--debug', help='Enable debug', action='store_true')
    parser.set_defaults(func=lambda: parser.print_help())
    sub_parsers = parser.add_subparsers()

    list_parser = sub_parsers.add_parser('list', aliases=['ls'], help='List stored programs')
    list_parser.set_defaults(func=handle_list)

    fwinfo_parser = sub_parsers.add_parser('fwinfo', help='Show firmware version')
    fwinfo_parser.set_defaults(func=handle_fwinfo)

    reboot_parser = sub_parsers.add_parser('reboot', help='Reboot hub')
    reboot_parser.set_defaults(func=handle_reboot)

    mvprogram_parser = sub_parsers.add_parser('mv', help='Changes program slot')
    mvprogram_parser.add_argument('from_slot', type=int)
    mvprogram_parser.add_argument('to_slot', type=int)
    mvprogram_parser.set_defaults(func=lambda: rpc.move_project(args.from_slot, args.to_slot))

    cpprogram_parser = sub_parsers.add_parser('upload', aliases=['cp'], help='Uploads a program')
    cpprogram_parser.add_argument('file')
    cpprogram_parser.add_argument('to_slot', type=int)
    cpprogram_parser.add_argument('name', nargs='?')
    cpprogram_parser.add_argument('--start', '-s', help='Start after upload', action='store_true')
    cpprogram_parser.set_defaults(func=handle_upload)

    rmprogram_parser = sub_parsers.add_parser('rm', help='Removes the program at a given slot')
    rmprogram_parser.add_argument('from_slot', type=int)
    rmprogram_parser.set_defaults(func=lambda: rpc.remove_project(args.from_slot))

    startprogram_parser = sub_parsers.add_parser('start', help='Starts a program')
    startprogram_parser.add_argument('slot', type=int)
    startprogram_parser.set_defaults(func=lambda: rpc.program_execute(args.slot))

    stopprogram_parser = sub_parsers.add_parser('stop', help='Stop program execution')
    stopprogram_parser.set_defaults(func=lambda: rpc.program_terminate())

    display_parser = sub_parsers.add_parser('display', help='Controls 5x5 LED matrix display')
    display_parser.set_defaults(func=lambda: display_parser.print_help())
    display_parsers = display_parser.add_subparsers()

    display_image_parser = display_parsers.add_parser('image', help='Displays image on the LED matrix')
    display_image_parser.add_argument('image',
                                      help='format xxxxx:xxxxx:xxxxx:xxxxx:xxxx, where x is the pixel brigthness in range 0-9')
    display_image_parser.set_defaults(func=lambda: rpc.display_image(args.image))

    display_text_parser = display_parsers.add_parser('text', help='Displays scrolling text on the LED matrix')
    display_text_parser.add_argument('text')
    display_text_parser.set_defaults(func=lambda: rpc.display_text(args.text))

    display_clear_parser = display_parsers.add_parser('clear', help='Clears display')
    display_clear_parser.set_defaults(func=lambda: rpc.display_clear())

    display_pixel_parser = display_parsers.add_parser('setpixel', help='Sets individual LED brightness')
    display_pixel_parser.add_argument('x', type=int)
    display_pixel_parser.add_argument('y', type=int)
    display_pixel_parser.add_argument('brightness', nargs='?', type=int, default=9, help='pixel brightness 0-9')
    display_pixel_parser.set_defaults(func=lambda: rpc.display_set_pixel(args.x, args.y, args.brightness))

    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    rpc = RPC(args.tty)
    args.func()
