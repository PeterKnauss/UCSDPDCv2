"""
Power supplies controlled through config files

PowerSupply class handles given supplies. Hardware config has connections and limits of each supply and model
config has the commands that the model understands. Voltage for each supply is from run config at supply_V.

    supplies = load_supplies(cfg["hardware"]["supplies"], cfg["run"]["supply_V"])
    connect_all(supplies)           # Open, check health and set protections. Outputs stay off
    ramp_up_all(supplies, ask)      # Ramp up in the order of hardware.yaml
    ramp_down_all(supplies)         # Ramp down in reverse order. Safe to call twice or before connect_all
"""
from __future__ import annotations

import math
import string
import time


class PowerError(RuntimeError):
    pass


def _dec(x: float) -> str:
    """5e-05 -> '0.00005' (python would print 5e-05, which the supply may not accept), 10 -> '10.0'"""
    s = f"{float(x):.8f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


# Every supply waits this long at its target voltage after the ramp up, so the bias settles before anything is measured
RAMP_UP_SETTLE_S = 1.5

_REQUIRED = ("terminations", "idn", "set_voltage", "health", "arm", "disarm")

# Options of open_resource that the model file sets
_FROM_MODEL = ("write_termination", "read_termination")


def _templates(p: dict) -> list[str]:
    """All the command text in a model file"""
    h, e = p.get("health", {}), p.get("ensure_off", {})
    out = [p.get("set_voltage", ""), *p.get("protect", []), *p.get("arm", []), *p.get("disarm", []),
           *h.get("after_ok", []), e.get("send", "")]
    for cmds in h.get("left_on", {}).values():
        out += cmds
    return out

def _ok_list(h: dict) -> list:
    """ok_contains as a list. It can be one text or a list of texts"""
    ok = h.get("ok_contains", [])
    return list(ok) if isinstance(ok, (list, tuple)) else [ok]

def check_profile(name: str, cfg: dict) -> list[str]:
    """Checks a supply and its model file for problems without touching hardware. Returns the list of problems"""
    p, model = cfg.get("profile") or {}, cfg.get("model")
    problems = [f"supply '{name}': model file '{model}' has no '{k}'" for k in _REQUIRED if k not in p]
    conn = cfg.get("connection")
    address = conn.get("address") if isinstance(conn, dict) else None
    if not isinstance(address, str) or not address.strip():
        problems.append(f"supply '{name}': connection.address = {address!r}: expected the text given to open_resource, "
                        f"like ASRL/dev/ttyUSB0::INSTR")
    else:
        problems += [f"supply '{name}': connection.{k} is set by 'terminations' in model file '{model}', not here"
                     for k in _FROM_MODEL if k in conn]
    h = p.get("health", {})
    for old in ("take", "ok"):
        if old in h:
            problems.append(f"supply '{name}': model file '{model}' health has '{old}', which is gone. Use ok_contains")
    if "ok_contains" not in h:
        problems.append(f"supply '{name}': model file '{model}' health has no 'ok_contains'")
    if "health_enable" in cfg and not isinstance(cfg["health_enable"], bool):
        problems.append(f"supply '{name}': health_enable = {cfg['health_enable']!r}: expected true or false")
    texts = _templates(p) + _ok_list(h) + list(h.get("left_on", {})) + list(p.get("ensure_off", {}))
    # Commands have to be text. YAML reads a bare on, off, yes or no as true or false
    for item in texts:
        if not isinstance(item, str):
            problems.append(f"supply '{name}': model file '{model}' has {item!r} where text is expected "
                            f"(quote it: YAML reads bare on/off/yes/no as true/false and 000001 as the number 1)")
    for item in _ok_list(h) + list(h.get("left_on", {})):
        if item == "":
            problems.append(f"supply '{name}': model file '{model}' has an empty health text, which matches every reply")
    if problems:
        return problems
    # Every {name} in a command has to be a number in the supply entry of hardware.yaml
    known = {"v"} | {k for k, v in cfg.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if "ovp_margin_V" in cfg:
        known.add("ovp_V")
    for text in _templates(p):
        for _, field, _, _ in string.Formatter().parse(text):
            if field and field not in known:
                problems.append(f"supply '{name}': model file '{model}' uses {{{field}}} in {text!r}, "
                                f"but the supply's entry in hardware.yaml has no '{field}'")
    return problems

def check_addresses(hw_cfg: dict) -> list[str]:
    """Problems with two supplies on the same address. Returns the list of problems"""
    seen, problems = {}, []
    for name, c in hw_cfg.items():
        address = (c.get("connection") or {}).get("address")
        if isinstance(address, str):
            if address in seen:
                problems.append(f"supply '{name}': connection.address is the same as supply '{seen[address]}'")
            seen.setdefault(address, name)
    return problems

def _visible(rm) -> list[str]:
    """Names of the resources pyvisa can see, for error messages"""
    try:
        return list(rm.list_resources())
    except Exception:
        return []


class PowerSupply:
    def __init__(self, name: str, cfg: dict, target_v: float):
        problems = check_profile(name, cfg)
        if problems:
            raise PowerError("\n".join(problems))
        self.name = name
        self.cfg = cfg
        self.profile = cfg["profile"]
        self.target_v = float(target_v)
        self.sleep = time.sleep
        self.inst = None
        # Last voltage sent to the supply
        self.volts = 0.0
        self.fields = {k: _dec(v) for k, v in cfg.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if "ovp_V" not in cfg:
            self.fields["ovp_V"] = _dec(self.target_v + cfg["ovp_margin_V"]) if "ovp_margin_V" in cfg else ""

    def open(self, rm) -> None:
        """Opens connection.address and prints the ID of the supply"""
        conn, t = dict(self.cfg["connection"]), self.profile["terminations"]
        address = conn.pop("address")
        # Everything else in connection is given to open_resource as it is
        opts = {"write_termination": t["write"], "read_termination": t["read"], **conn}
        print("opening resource: " + address)
        try:
            self.inst = rm.open_resource(address, **opts)
        except Exception as ex:
            raise PowerError(f"{self.name}: could not open {address}: {ex}\n"
                             f"resources pyvisa can see: {_visible(rm)}") from ex
        try:
            reply = self.query(self.profile["idn"])
        except Exception as ex:
            raise PowerError(f"{self.name}: no reply to {self.profile['idn']!r} from {address}: {ex}") from ex
        print(f"{self.name} device: {reply}")

    def close(self) -> None:
        """Closes the resource without sending anything"""
        if self.inst is not None:
            self.inst.close()
            self.inst = None

    def write(self, text: str, **kw) -> None:
        """Sends a command with the numbers of the supply filled in"""
        self.inst.write(text.format(**self.fields, **kw))

    def query(self, text: str) -> str:
        """Sends a query and returns the reply"""
        return self.inst.query(text)
    
    def prepare(self) -> None:
        """Checks the health, turns off what a previous run left on and sets the protections. Output stays off"""
        p = self.profile
        if self.cfg.get("health_enable", True):
            self.check_health()
        else:
            print(f"{self.name}: health check is off")
        e = p.get("ensure_off")
        if e and int(self.query(e["query"])) == int(e["on_value"]):
            print("output is on - turn it off")
            self.write(e["send"])
        if p.get("protect"):
            print(f"{self.name}: setting protection limits")
        for cmd in p.get("protect", []):
            self.write(cmd)

    def check_health(self) -> None:
        """Asks for the health. A reply with left_on text gets those commands. A reply with ok_contains text is good"""
        h = self.profile["health"]
        reply = self.query(h["query"])
        for text, cmds in h.get("left_on", {}).items():
            if text in reply:
                print(f"{self.name}: settings remain from previous run ({reply}) - turning them off")
                for cmd in cmds:
                    self.write(cmd)
                return
        if any(text in reply for text in _ok_list(h)):
            print("All good")
            for cmd in h.get("after_ok", []):
                self.write(cmd)
            return
        raise PowerError(f"{self.name}: failed system health: {reply}")

    def set_voltage(self, v: float) -> None:
        """Sets the voltage and remembers it"""
        self.write(self.profile["set_voltage"], v=_dec(v))
        self.volts = float(v)

    @staticmethod
    def _steps(start: float, stop: float, step: float) -> list[float]:
        """start, start+step, ... while below stop"""
        return [start + i * step for i in range(max(0, math.ceil((stop - start) / step - 1e-9)))]

    def up_levels(self) -> list[float]:
        """Voltages for the ramp up. Slow steps below slow_start_V, then step_V steps, and always ends on the target"""
        c = self.cfg
        slow = min(float(c.get("slow_start_V", 0)), self.target_v)
        return (self._steps(0.0, slow, float(c.get("slow_step_V", 1)))
                + self._steps(slow, self.target_v, float(c["step_V"]))
                + [self.target_v])

    def down_levels(self) -> list[float]:
        """Voltages for the ramp down. From the last voltage sent to 0 in step_V steps"""
        step = float(self.cfg["step_V"])
        return [self.volts - i * step for i in range(math.ceil(self.volts / step - 1e-9))] + [0.0]

    def ramp_up(self, ask) -> None:
        """Ramps the supply up. ask(prompt) is PdcSession.prompt, which is input() or just a print in batch mode"""
        ask(f"Apply {self.name} output ({self.target_v:g} V)?")
        for cmd in self.profile["arm"]:
            self.write(cmd)
        print(f"{self.name} ramping up....")
        for v in self.up_levels():
            self.sleep(self.cfg["step_delay_s"])
            self.set_voltage(v)
        print(f"{self.name} is supplied. Waiting {RAMP_UP_SETTLE_S:g} s to settle")
        self.sleep(RAMP_UP_SETTLE_S)

    def ramp_down(self) -> None:
        """Ramps the supply down from the last voltage sent"""
        if self.volts <= 0:
            return
        print(f"{self.name} ramping down....")
        for v in self.down_levels():
            self.sleep(self.cfg["step_delay_s"])
            self.set_voltage(v)
        print(f"{self.name} is turned off")

    def shutdown(self) -> None:
        """Ramps down, turns off and closes the supply. Safe to call twice or before the supply was opened"""
        if self.inst is None:
            return
        self.ramp_down()
        for cmd in self.profile["disarm"]:
            self.write(cmd)
        self.inst.close()
        self.inst = None
        self.volts = 0.0

def load_supplies(hw_cfg: dict, targets_v: dict) -> list[PowerSupply]:
    """Makes one supply per entry of hardware.supplies in file order. targets_v is run.supply_V. Does not touch hardware"""
    problems = check_addresses(hw_cfg)
    if problems:
        raise PowerError("\n".join(problems))
    supplies = []
    for name, c in hw_cfg.items():
        if name not in targets_v:
            raise PowerError(f"supply '{name}': no voltage in run.supply_V")
        supplies.append(PowerSupply(name, c, targets_v[name]))
    return supplies

def connect_all(supplies: list[PowerSupply]) -> None:
    """Opens every supply, then prepares them in order. If one cannot be opened the others are closed without sending anything"""
    import pyvisa
    rm = pyvisa.ResourceManager("@py")
    try:
        for s in supplies:
            s.open(rm)
    except BaseException:
        for s in supplies:
            s.close()
        raise
    for s in supplies:
        s.prepare()

def ramp_up_all(supplies: list[PowerSupply], ask) -> None:
    """Ramps up each supply in order"""
    for s in supplies:
        s.ramp_up(ask)
    ask("Press [enter] key to continue")

def ramp_down_all(supplies: list[PowerSupply]) -> None:
    """Ramps down in reverse order. Safe to call twice or when nothing was connected"""
    if any(s.inst is not None for s in supplies):
        print("Turn off power supplies")
    for s in reversed(supplies):
        s.shutdown()
