#
# Part of info-beamer hosted. You can find the latest version
# of this file at:
#
# https://github.com/info-beamer/package-sdk
#
# Copyright (c) 2014-2020 Florian Wesch <fw@info-beamer.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#
#     Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the
#     distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

VERSION = "1.6"

import os, re, sys, json, time, traceback, marshal, hashlib
import errno, socket, select, thread, threading
import pyinotify, requests
from functools import wraps
from collections import namedtuple
from tempfile import NamedTemporaryFile

types = {}

def init_types():
    def type(fn):
        types[fn.__name__] = fn
        return fn

    @type
    def color(value):
        return value

    @type
    def string(value):
        return value

    @type
    def text(value):
        return value

    @type
    def section(value):
        return value

    @type
    def boolean(value):
        return value

    @type
    def select(value):
        return value

    @type
    def duration(value):
        return value

    @type
    def integer(value):
        return value

    @type
    def float(value):
        return value

    @type
    def font(value):
        return value

    @type
    def device(value):
        return value

    @type
    def resource(value):
        return value

    @type
    def json(value):
        return value

    @type
    def custom(value):
        return value

    @type
    def date(value):
        return value

init_types()

def log(msg, name='hosted.py'):
    print >>sys.stderr, "[{}] {}".format(name, msg)

def abort_service(reason):
    log("restarting service (%s)" % reason)
    try:
        thread.interrupt_main()
    except:
        pass
    time.sleep(2)
    os.kill(os.getpid(), 2)
    time.sleep(2)
    os.kill(os.getpid(), 15)
    time.sleep(2)
    os.kill(os.getpid(), 9)
    time.sleep(100)

class InfoBeamerQueryException(Exception):
    pass

class InfoBeamerQuery(object):
    def __init__(self, host='127.0.0.1', port=4444):
        self._sock = None
        self._conn = None
        self._host = host
        self._port = port
        self._timeout = 2
        self._version = None

    def _reconnect(self):
        if self._conn is not None:
            return
        try:
            self._sock = socket.create_connection((self._host, self._port), self._timeout)
            self._conn = self._sock.makefile()
            intro = self._conn.readline()
        except socket.timeout:
            self._reset()
            raise InfoBeamerQueryException("Timeout while reopening connection")
        except socket.error as err:
            self._reset()
            raise InfoBeamerQueryException("Cannot connect to %s:%s: %s" % (
                self._host, self._port, err))
        m = re.match("^Info Beamer PI ([^ ]+)", intro)
        if not m:
            self._reset()
            raise InfoBeamerQueryException("Invalid handshake. Not info-beamer?")
        self._version = m.group(1)

    def _parse_line(self):
        line = self._conn.readline()
        if not line:
            return None
        return line.rstrip()

    def _parse_multi_line(self):
        lines = []
        while 1:
            line = self._conn.readline()
            if not line:
                return None
            line = line.rstrip()
            if not line:
                break
            lines.append(line)
        return '\n'.join(lines)

    def _send_cmd(self, min_version, cmd, multiline=False):
        for retry in (1, 2):
            self._reconnect()
            if self._version <= min_version:
                raise InfoBeamerQueryException(
                    "This query is not implemented in your version of info-beamer. "
                    "%s or higher required, %s found" % (min_version, self._version)
                )
            try:
                self._conn.write(cmd + "\n")
                self._conn.flush()
                response = self._parse_multi_line() if multiline else self._parse_line()
                if response is None:
                    self._reset()
                    continue
                return response
            except socket.error:
                self._reset()
                continue
            except socket.timeout:
                self._reset()
                raise InfoBeamerQueryException("Timeout waiting for response")
            except Exception:
                self._reset()
                continue
        raise InfoBeamerQueryException("Failed to get a response")

    def _reset(self, close=True):
        if close:
            try:
                if self._conn: self._conn.close()
                if self._sock: self._sock.close()
            except:
                pass
        self._conn = None
        self._sock = None

    @property
    def addr(self):
        return "%s:%s" % (self._host, self._port)

    def close(self):
        self._reset()

    @property
    def ping(self):
        "tests if info-beamer is reachable"
        return self._send_cmd(
            "0.6", "*query/*ping",
        ) == "pong"

    @property
    def uptime(self):
        "returns the uptime in seconds"
        return int(self._send_cmd(
            "0.6", "*query/*uptime",
        ))

    @property
    def objects(self):
        "returns the number of allocated info-beamer objects"
        return int(self._send_cmd(
            "0.9.4", "*query/*objects",
        ))

    @property
    def version(self):
        "returns the running info-beamer version"
        return self._send_cmd(
            "0.6", "*query/*version",
        )

    @property
    def fps(self):
        "returns the FPS of the top level node"
        return float(self._send_cmd(
            "0.6", "*query/*fps",
        ))

    @property
    def display(self):
        "returns the display configuration"
        return json.loads(self._send_cmd(
            "1.0", "*query/*display",
        ))

    ResourceUsage = namedtuple("ResourceUsage", "user_time system_time memory")
    @property
    def resources(self):
        "returns information about used resources"
        return self.ResourceUsage._make(int(v) for v in self._send_cmd(
            "0.6", "*query/*resources",
        ).split(','))

    ScreenSize = namedtuple("ScreenSize", "width height")
    @property
    def screen(self):
        "returns the native screen size"
        return self.ScreenSize._make(int(v) for v in self._send_cmd(
            "0.8.1", "*query/*screen",
        ).split(','))

    @property
    def runid(self):
        "returns a unique run id that changes with every restart of info-beamer"
        return self._send_cmd(
            "0.9.0", "*query/*runid",
        )

    @property
    def nodes(self):
        "returns a list of nodes"
        nodes = self._send_cmd(
            "0.9.3", "*query/*nodes",
        ).split(',')
        return [] if not nodes[0] else nodes

    class Node(object):
        def __init__(self, ib, path):
            self._ib = ib
            self._path = path

        @property
        def mem(self):
            "returns the Lua memory usage of this node"
            return int(self._ib._send_cmd(
                "0.6", "*query/*mem/%s" % self._path
            ))

        @property
        def fps(self):
            "returns the framerate of this node"
            return float(self._ib._send_cmd(
                "0.6", "*query/*fps/%s" % self._path
            ))

        def io(self, raw=True):
            "creates a tcp connection to this node"
            status = self._ib._send_cmd(
                "0.6", "%s%s" % ("*raw/" if raw else '', self._path),
            )
            if status != 'ok!':
                raise InfoBeamerQueryException("Cannot connect to node %s" % self._path)
            sock = self._ib._sock
            sock.settimeout(None)
            return self._ib._conn

        @property
        def has_error(self):
            "queries the error flag"
            return bool(int(self._ib._send_cmd(
                "0.8.2", "*query/*has_error/%s" % self._path,
            )))

        @property
        def error(self):
            "returns the last Lua traceback"
            return self._ib._send_cmd(
                "0.8.2", "*query/*error/%s" % self._path, multiline=True
            )

        def __repr__(self):
            return "%s/%s" % (self._ib, self._path)

    def node(self, node):
        return self.Node(self, node)

    def __repr__(self):
        return "<info-beamer@%s>" % self.addr


class Configuration(object):
    def __init__(self):
        self._restart = False
        self._options = []
        self._config = {}
        self._parsed = {}
        self.parse_node_json(do_update=False)
        self.parse_config_json()

    def restart_on_update(self):
        log("going to restart when config is updated")
        self._restart = True

    def parse_node_json(self, do_update=True):
        with open("node.json") as f:
            self._options = json.load(f).get('options', [])
        if do_update:
            self.update_config()

    def parse_config_json(self, do_update=True):
        with open("config.json") as f:
            self._config = json.load(f)
        if do_update:
            self.update_config()

    def update_config(self):
        if self._restart:
            return abort_service("restart_on_update set")

        def parse_recursive(options, config, target):
            # print 'parsing', config
            for option in options:
                if not 'name' in option:
                    continue
                if option['type'] == 'list':
                    items = []
                    for item in config[option['name']]:
                        parsed = {}
                        parse_recursive(option['items'], item, parsed)
                        items.append(parsed)
                    target[option['name']] = items
                    continue
                target[option['name']] = types[option['type']](config[option['name']])

        parsed = {}
        parse_recursive(self._options, self._config, parsed)
        log("updated config")
        self._parsed = parsed

    @property
    def raw(self):
        return self._config

    @property
    def metadata(self):
        return self._config['__metadata']

    def __getitem__(self, key):
        return self._parsed[key]

    def __getattr__(self, key):
        return self._parsed[key]

def setup_inotify(configuration):
    class EventHandler(pyinotify.ProcessEvent):
        def process_default(self, event):
            basename = os.path.basename(event.pathname)
            if basename == 'node.json':
                log("node.json changed")
                configuration.parse_node_json()
            elif basename == 'config.json':
                log("config.json changed!")
                configuration.parse_config_json()
            elif basename.endswith('.py'):
                abort_service("python file changed")

    wm = pyinotify.WatchManager()

    notifier = pyinotify.ThreadedNotifier(wm, EventHandler())
    notifier.daemon = True
    notifier.start()

    wm.add_watch('.', pyinotify.IN_MOVED_TO)

class RPC(object):
    def __init__(self, path, callbacks):
        self._path = path
        self._callbacks = callbacks
        self._lock = threading.Lock()
        self._con = None
        thread = threading.Thread(target=self._listen_thread)
        thread.daemon = True
        thread.start()

    def _get_connection(self):
        if self._con is None:
            try:
                self._con = InfoBeamerQuery().node(
                    self._path + "/rpc/python"
                ).io(raw=True)
            except InfoBeamerQueryException:
                return None
        return self._con

    def _close_connection(self):
        with self._lock:
            if self._con:
                try:
                    self._con.close()
                except:
                    pass
            self._con = None

    def _send(self, line):
        with self._lock:
            con = self._get_connection()
        if con is None:
            return
        try:
            con.write(line + '\n')
            con.flush()
            return True
        except:
            self._close_connection()
            return False

    def _recv(self):
        with self._lock:
            con = self._get_connection()
        try:
            return con.readline()
        except:
            self._close_connection()

    def _listen_thread(self):
        while 1:
            line = self._recv()
            if not line:
                self._close_connection()
                time.sleep(0.5)
                continue
            try:
                args = json.loads(line)
                method = args.pop(0)
                callback = self._callbacks.get(method)
                if callback:
                    callback(*args)
                else:
                    log("callback '%s' not found" % (method,))
            except:
                traceback.print_exc()

    def register(self, name, fn):
        self._callbacks[name] = fn

    def call(self, fn):
        self.register(fn.__name__, fn)

    def __getattr__(self, method):
        def call(*args):
            args = list(args)
            args.insert(0, method)
            return self._send(json.dumps(
                args,
                ensure_ascii=False,
                separators=(',',':'),
            ).encode('utf8'))
        return call

class Cache(object):
    def __init__(self, scope='default'):
        self._touched = set()
        self._prefix = 'cache-%s-' % scope

    def key_to_fname(self, key):
        return self._prefix + hashlib.md5(key).hexdigest()

    def has(self, key, max_age=None):
        try:
            stat = os.stat(self.key_to_fname(key))
            if max_age is not None:
                now = time.time()
                if now > stat.st_mtime + max_age:
                    return False
            return True
        except:
            return False

    def get(self, key, max_age=None):
        try:
            with open(self.file_ref(key)) as f:
                if max_age is not None:
                    stat = os.fstat(f.fileno())
                    now = time.time()
                    if now > stat.st_mtime + max_age:
                        return None
                return f.read()
        except:
            return None

    def get_json(self, key, max_age=None):
        data = self.get(key, max_age)
        if data is None:
            return None
        return json.loads(data)

    def set(self, key, value):
        with open(self.file_ref(key), "wb") as f:
            f.write(value)

    def set_json(self, key, data):
        self.set(key, json.dumps(data))

    def file_ref(self, key):
        fname = self.key_to_fname(key)
        self._touched.add(fname)
        return fname

    def start(self):
        self._touched = set()

    def prune(self):
        existing = set()
        for fname in os.listdir("."):
            if not fname.startswith(self._prefix):
                continue
            existing.add(fname)
        prunable = existing - self._touched
        for fname in prunable:
            try:
                log("pruning %s" % fname)
                os.unlink(fname)
            except:
                pass

    def clear(self):
        self.start()
        self.prune()

    def call(self, max_age=None):
        def deco(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                key = marshal.dumps((fn.__name__, args, kwargs), 2)
                cached = self.get(key, max_age)
                if cached is not None:
                    return marshal.loads(cached)
                val = fn(*args, **kwargs)
                self.set(key, marshal.dumps(val, 2))
                return val
            return wrapper
        return deco

    def file_producer(self, max_age=None):
        def deco(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                key = marshal.dumps((fn.__name__, args, kwargs), 2)
                if self.has(key, max_age):
                    return self.file_ref(key)
                val = fn(*args, **kwargs)
                if val is None:
                    return None
                self.set(key, val)
                return self.file_ref(key)
            return wrapper
        return deco

class Node(object):
    def __init__(self, node):
        self._node = node
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_raw(self, raw):
        log("sending %r" % (raw,))
        self._sock.sendto(raw, ('127.0.0.1', 4444))

    def send(self, data):
        self.send_raw(self._node + data)

    @property
    def is_top_level(self):
        return self._node == "root"

    @property
    def path(self):
        return self._node

    def write_file(self, filename, content):
        f = NamedTemporaryFile(prefix='.hosted-py-tmp', dir=os.getcwd())
        try:
            f.write(content)
        except:
            traceback.print_exc()
            f.close()
            raise
        else:
            f.delete = False
            f.close()
            os.rename(f.name, filename)

    def write_json(self, filename, data):
        self.write_file(filename, json.dumps(
            data,
            ensure_ascii=False,
            separators=(',',':'),
        ).encode('utf8'))

    class Sender(object):
        def __init__(self, node, path):
            self._node = node
            self._path = path

        def __call__(self, data):
            if isinstance(data, (dict, list)):
                raw = "%s:%s" % (self._path, json.dumps(
                    data,
                    ensure_ascii=False,
                    separators=(',',':'),
                ).encode('utf8'))
            else:
                raw = "%s:%s" % (self._path, data)
            self._node.send_raw(raw)

    def __getitem__(self, path):
        return self.Sender(self, self._node + path)

    def __call__(self, data):
        return self.Sender(self, self._node)(data)

    def connect(self, suffix=""):
        ib = InfoBeamerQuery()
        return ib.node(self.path + suffix).io(raw=True)

    def rpc(self, **callbacks):
        return RPC(self.path, callbacks)

    def cache(self, scope='default'):
        return Cache(scope)

    def scratch_cached(self, filename, generator):
        cached = os.path.join(os.environ['SCRATCH'], filename)

        if not os.path.exists(cached):
            f = NamedTemporaryFile(prefix='scratch-cached-tmp', dir=os.environ['SCRATCH'])
            try:
                generator(f)
            except:
                raise
            else:
                f.delete = False
                f.close()
                os.rename(f.name, cached)

        if os.path.exists(filename):
            try:
                os.unlink(filename)
            except:
                pass
        os.symlink(cached, filename)

class APIError(Exception):
    pass

class APIProxy(object):
    def __init__(self, apis, api_name):
        self._apis = apis
        self._api_name = api_name

    @property
    def url(self):
        index = self._apis.get_api_index()
        if not self._api_name in index:
            raise APIError("api '%s' not available" % (self._api_name,))
        return index[self._api_name]['url']

    def unwrap(self, r):
        r.raise_for_status()
        if r.status_code == 304:
            return None
        if r.headers['content-type'] == 'application/json':
            resp = r.json()
            if not resp['ok']:
                raise APIError(u"api call failed: %s" % (
                    resp.get('error', '<unknown error>'),
                ))
            return resp.get(self._api_name)
        else:
            return r.content

    def add_defaults(self, kwargs):
        if not 'timeout' in kwargs:
            kwargs['timeout'] = 10

    def get(self, **kwargs):
        self.add_defaults(kwargs)
        try:
            return self.unwrap(self._apis.session.get(
                url = self.url,
                **kwargs
            ))
        except APIError:
            raise
        except Exception as err:
            raise APIError(err)

    def post(self, **kwargs):
        self.add_defaults(kwargs)
        try:
            return self.unwrap(self._apis.session.post(
                url = self.url,
                **kwargs
            ))
        except APIError:
            raise
        except Exception as err:
            raise APIError(err)

class OnDeviceAPIs(object):
    def __init__(self, config):
        self._config = config
        self._index = None
        self._valid_until = 0
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'hosted.py version/%s' % (VERSION,)
        })

    def update_apis(self):
        log("fetching api index")
        r = self._session.get(
            url = self._config.metadata['api'],
            timeout = 5,
        )
        r.raise_for_status()
        resp = r.json()
        if not resp['ok']:
            raise APIError("cannot retrieve api index")
        self._index = resp['apis']
        self._valid_until = resp['valid_until'] - 300

    def get_api_index(self):
        with self._lock:
            now = time.time()
            if now > self._valid_until:
                self.update_apis()
            return self._index

    @property
    def session(self):
        return self._session

    def list(self):
        try:
            index = self.get_api_index()
            return sorted(index.keys())
        except Exception as err:
            raise APIError(err)

    def __getitem__(self, api_name):
        return APIProxy(self, api_name)

    def __getattr__(self, api_name):
        return APIProxy(self, api_name)

class GPIO(object):
    def __init__(self):
        self._pin_fd = {}
        self._state = {}
        self._fd_2_pin = {}
        self._poll = select.poll()
        self._lock = threading.Lock()

    def setup_pin(self, pin, direction="in", invert=False):
        if not os.path.exists("/sys/class/gpio/gpio%d" % pin):
            with open("/sys/class/gpio/export", "wb") as f:
                f.write(str(pin))
        # mdev is giving the newly create GPIO directory correct permissions.
        for i in range(10):
            try:
                with open("/sys/class/gpio/gpio%d/active_low" % pin, "wb") as f:
                    f.write("1" if invert else "0")
                break
            except IOError as err:
                if err.errno != errno.EACCES:
                    raise
            time.sleep(0.1)
            log("waiting for GPIO permissions")
        else:
            raise IOError(errno.EACCES, "Cannot access GPIO")
        with open("/sys/class/gpio/gpio%d/direction" % pin, "wb") as f:
            f.write(direction)

    def set_pin_value(self, pin, high):
        with open("/sys/class/gpio/gpio%d/value" % pin, "wb") as f:
            f.write("1" if high else "0")

    def monitor(self, pin, invert=False):
        if pin in self._pin_fd:
            return
        self.setup_pin(pin, direction="in", invert=invert)
        with open("/sys/class/gpio/gpio%d/edge" % pin, "wb") as f:
            f.write("both")
        fd = os.open("/sys/class/gpio/gpio%d/value" % pin, os.O_RDONLY)
        self._state[pin] = bool(int(os.read(fd, 5)))
        self._fd_2_pin[fd] = pin
        self._pin_fd[pin] = fd
        self._poll.register(fd, select.POLLPRI | select.POLLERR)

    def poll(self, timeout=1000):
        changes = []
        for fd, evt in self._poll.poll(timeout):
            os.lseek(fd, 0, 0)
            state = bool(int(os.read(fd, 5)))
            pin = self._fd_2_pin[fd]
            with self._lock:
                prev_state, self._state[pin] = self._state[pin], state
            if state != prev_state:
                changes.append((pin, state))
        return changes

    def poll_forever(self):
        while 1:
            for event in self.poll():
                yield event

    def on(self, pin):
        with self._lock:
            return self._state.get(pin, False)

class SyncerAPI(object):
    def __init__(self):
        self._session = requests.Session()

    def unwrap(self, r):
        r.raise_for_status()
        return r.json()

    def get(self, path, params={}):
        return self.unwrap(self._session.get(
            'http://127.0.0.1:81%s' % path,
            params=params, timeout=10
        ))

    def post(self, path, data={}):
        return self.unwrap(self._session.post(
            'http://127.0.0.1:81%s' % path,
            data=data, timeout=10
        ))

class Device(object):
    def __init__(self):
        self._socket = None
        self._gpio = GPIO()

    @property
    def gpio(self):
        return self._gpio

    @property
    def serial(self):
        return os.environ['SERIAL']

    @property
    def screen_resolution(self):
        with open("/sys/class/graphics/fb0/virtual_size", "rb") as f:
            return [int(val) for val in f.read().strip().split(',')]

    @property
    def screen_w(self):
        return self.screen_resolution[0]

    @property
    def screen_h(self):
        return self.screen_resolution[1]

    def ensure_connected(self):
        if self._socket:
            return True
        try:
            log("establishing upstream connection")
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.connect(os.getenv('SYNCER_SOCKET', "/tmp/syncer"))
            return True
        except Exception as err:
            log("cannot connect to upstream socket: %s" % (err,))
            return False

    def send_raw(self, raw):
        try:
            if self.ensure_connected():
                self._socket.send(raw + '\n')
        except Exception as err:
            log("cannot send to upstream: %s" % (err,))
            if self._socket:
                self._socket.close()
            self._socket = None

    def send_upstream(self, **data):
        self.send_raw(json.dumps(data))

    def turn_screen_off(self):
        self.send_raw("tv off")

    def turn_screen_on(self):
        self.send_raw("tv on")

    def screen(self, on=True):
        if on:
            self.turn_screen_on()
        else:
            self.turn_screen_off()

    def reboot(self):
        self.send_raw("system reboot")

    def halt_until_powercycled(self):
        self.send_raw("system halt")

    def restart_infobeamer(self):
        self.send_raw("infobeamer restart")

    def verify_cache(self):
        self.send_raw("syncer verify_cache")

    @property
    def syncer_api(self):
        return SyncerAPI()

if __name__ == "__main__":
    device = Device()
    while 1:
        try:
            command = raw_input("syncer> ")
            device.send_raw(command)
        except (KeyboardInterrupt, EOFError):
            break
        except:
            traceback.print_exc()
else:
    log("starting version %s" % (VERSION,))
    node = NODE = Node(os.environ['NODE'])
    device = DEVICE = Device()
    config = CONFIG = Configuration()
    api = API = OnDeviceAPIs(CONFIG)
    setup_inotify(CONFIG)
    log("ready to go!")
