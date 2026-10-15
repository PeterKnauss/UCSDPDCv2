"""
Mode: what a run does after the shared init.

    Mode(session).execute()

runs, in this order:
    prepare_data_path()   mode-specific Zynq/data setup (before the Controller helper exists)
    session.initialize()  the shared init sequence (see session.py)
    configure()           mode-specific stages after the PDCs are configured
    power_up()            connect the supplies, ask for HV, ramp up
    run()                 the measurement
    finish()              always runs, also after Ctrl-C or an error: ramps the supplies down, stops the Zynq side
"""
from __future__ import annotations
import time
from ..power import PowerError, PowerSupply, connect_all, load_supplies, ramp_down_all, ramp_up_all
from ..session import PdcSession, section


class Mode:
    def __init__(self, session: PdcSession):
        self.session = session
        self.cfg = session.cfg
        self.power: list[PowerSupply] | None = None
        self.test_start_time = time.time()

    # Three functions that are required to be defined on a per-Mode basis to be called
    def prepare_data_path(self) -> None: ...
    def configure(self) -> None: ...
    def run(self) -> None: ...

    def stage_send(self, title, group) -> None:
        """Stages a send call to print a title if it exists"""
        if self.session.plan[group]:
            section(title)
            self.session.send(group)
        else:
            print(f"Nothing to send for plan group {group}")

    def power_up(self) -> None:
        """Automatically ramps up the supplies in hardware.yaml unless manual HV is requested"""
        s = self.session
        if not self.cfg["behavior"].get("power_supplies"):
            # Request user to manually turn on the power supplies
            print("Apply HV here")
            s.prompt("Press [enter] key to continue")
            return
        section("set up power supplies")
        self.power = load_supplies(self.cfg["hardware"]["supplies"], self.cfg["run"]["supply_V"])
        connect_all(self.power)
        print("Apply HV here")
        ramp_up_all(self.power, ask=s.prompt)

    def finish(self) -> None:
        """Ramp down power supply if it was turned on"""
        if self.power is not None:
            ramp_down_all(self.power)

    def execute(self) -> None:
        """Main execution loop"""
        s = self.session
        try:
            self.prepare_data_path()
            s.initialize()
            self.configure()
            self.power_up()
            self.run()
        except KeyboardInterrupt:
            print("\nKeyboard Interrupt: exit program")
        except PowerError as ex:
            print(f"\nPOWER SUPPLY ERROR: {ex}")
            raise
        except SystemExit:
            print("\nProgram interrupted: exit program")
            raise
        finally:
            self.finish()
