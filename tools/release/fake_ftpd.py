"""An in-process ftpd on 127.0.0.1 for the builder's save-import tests (loopback only, ephemeral ports, stdlib only).

The same fake as the development tree's FTP staging tests use; never a console, and port 17491 (3dslink) is never
used.
"""
import os
from pathlib import Path
import socket
import socketserver
import threading
import time

NETLOADER_PORT = 17491  # 3dslink; a bare connect crashes the Homebrew Launcher's netloader


class FakeFtpd:
    """Enough of a 3DS ftpd for ftplib: USER/PASS, TYPE, PASV, MLSD, SIZE, MKD, STOR, RETR, RNFR/RNTO, DELE, QUIT.

    Fault knobs (each a {path substring: remaining count} dict, consumed per hit):
      drop_stor     read about half of the upload, then drop data and control connections (lid closed, Wi-Fi blip)
      short_stor    keep only half of the upload but answer 226 (a short write)
      corrupt_stor  flip the first byte of the upload
      perm_stor     answer 552 (card full); count -1 means always
    refuse: the next N connections are closed straight after accept.
    Renaming onto an existing name fails with 550, as on the card.
    """

    def __init__(self, root, banner='220 fake ftpd'):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cmds, self.refuse, self.connections = [], 0, 0
        self.drop_stor, self.short_stor, self.corrupt_stor, self.perm_stor = {}, {}, {}, {}
        self.getmtime = True
        self.banner = banner
        self.missing_reply = '550 none'
        self.mkd_exists_reply = '550 exists'  # ftpd v2.3.1 sends '250 OK' when the folder already exists.
        self.after_retr = self.after_rename = None
        self.lock = threading.Lock()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, s):
                self.wfile.write((s + "\r\n").encode())
                self.wfile.flush()

            def handle(self):
                with outer.lock:
                    outer.connections += 1
                    if outer.refuse > 0:
                        outer.refuse -= 1
                        return
                self.reply(outer.banner)
                pasv, rnfr = None, None
                cwd, restart = '/', 0
                while True:
                    try:
                        line = self.rfile.readline().decode()
                    except OSError:
                        return
                    if not line:
                        return
                    cmd, _, arg = line.strip().partition(" ")
                    cmd = cmd.upper()
                    with outer.lock:
                        outer.cmds.append((cmd, arg))
                    local = outer.local(arg)
                    if cmd == "USER":
                        self.reply("331 ok")
                    elif cmd == "PASS":
                        self.reply("230 ok")
                    elif cmd in ("TYPE", "NOOP"):
                        self.reply("200 ok")
                    elif cmd == 'PWD':
                        self.reply('257 "%s"' % cwd)
                    elif cmd == 'CWD':
                        if local.is_dir():
                            cwd = arg
                            self.reply('250 changed')
                        else:
                            self.reply('550 no such folder')
                    elif cmd == 'REST':
                        restart = int(arg)
                        self.reply('350 restart position accepted')
                    elif cmd == "OPTS":
                        self.reply("200 MLST facts selected")
                    elif cmd == "PASV":
                        pasv = socket.socket()
                        pasv.bind(("127.0.0.1", 0))
                        pasv.listen(1)
                        port = pasv.getsockname()[1]
                        self.reply("227 Entering Passive Mode (127,0,0,1,%d,%d)" % (port >> 8, port & 255))
                    elif cmd == "MLSD":
                        if not local.is_dir():
                            pasv.close()
                            self.reply("550 No such file or directory")  # ftpd: 550 and strerror(ENOENT).
                            continue
                        self.reply("150 listing")
                        conn, _ = pasv.accept()
                        for p in sorted(local.iterdir()):
                            kind = "dir" if p.is_dir() else "file"
                            size = ";size=%d" % p.stat().st_size if kind == "file" else ""
                            ns = p.stat().st_mtime_ns
                            stamp = time.strftime('%Y%m%d%H%M%S', time.gmtime(ns // 10**9)) + '.%09d' % (ns % 10**9)
                            if not outer.getmtime:
                                stamp = '19700101000000'
                            conn.sendall(("type=%s%s;modify=%s; %s\r\n" % (kind, size, stamp, p.name)).encode())
                        conn.close()
                        pasv.close()
                        self.reply("226 done")
                    elif cmd == "SIZE":
                        self.reply("213 %d" % local.stat().st_size if local.is_file() else outer.missing_reply)
                    elif cmd == "MKD":
                        if local.exists():
                            self.reply(outer.mkd_exists_reply)
                        elif not local.parent.is_dir():
                            self.reply("550 no parent")
                        else:
                            local.mkdir()
                            self.reply('257 "%s" created' % arg)
                    elif cmd == "STOR":
                        if outer.take(outer.perm_stor, arg):
                            pasv.close()
                            self.reply("552 card full")
                            continue
                        if local.is_dir() or not local.parent.is_dir():
                            pasv.close()
                            self.reply("550 bad path")
                            continue
                        self.reply("150 send")
                        conn, _ = pasv.accept()
                        drop = outer.take(outer.drop_stor, arg)
                        data = bytearray(local.read_bytes()[:restart]) if restart and local.is_file() else bytearray()
                        restart = 0
                        while True:
                            b = conn.recv(65536)
                            if not b:
                                break
                            data += b
                            if drop and len(data) >= 4096:
                                break
                        if drop:
                            local.write_bytes(bytes(data[:len(data) // 2]))
                            conn.close()
                            pasv.close()
                            return                   # control connection dropped, no reply
                        if outer.take(outer.short_stor, arg):
                            data = data[:len(data) // 2]
                        if data and outer.take(outer.corrupt_stor, arg):
                            data[0] ^= 0xFF
                        local.write_bytes(bytes(data))
                        conn.close()
                        pasv.close()
                        self.reply("226 stored")
                    elif cmd == "RETR":
                        if not local.is_file():
                            pasv.close()
                            self.reply("550 none")
                            continue
                        self.reply("150 sending")
                        conn, _ = pasv.accept()
                        conn.sendall(local.read_bytes())
                        if outer.after_retr:
                            outer.after_retr(arg)
                        conn.close()
                        pasv.close()
                        self.reply("226 sent")
                    elif cmd == "RNFR":
                        rnfr = local if local.exists() else None
                        self.reply("350 ready" if rnfr else "550 none")
                    elif cmd == "RNTO":
                        if rnfr is None or local.exists():
                            self.reply("550 cannot rename")
                        else:
                            os.rename(rnfr, local)
                            if outer.after_rename:
                                outer.after_rename(arg)
                            self.reply("250 renamed")
                        rnfr = None
                    elif cmd == "DELE":
                        if local.is_file():
                            local.unlink()
                            self.reply("250 deleted")
                        else:
                            self.reply(outer.missing_reply)
                    elif cmd == "QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("502 not here")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        assert self.port != NETLOADER_PORT
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def local(self, arg):
        return self.root.joinpath(*[p for p in arg.split("/") if p])

    def take(self, knob, path):
        with self.lock:
            for key, left in knob.items():
                if key in path and left != 0:
                    knob[key] = left - 1 if left > 0 else left
                    return True
        return False

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def written(self):
        """Paths given to STOR, RNTO and DELE."""
        return [(c, a) for c, a in self.cmds if c in ("STOR", "RNTO", "DELE", "RNFR")]
