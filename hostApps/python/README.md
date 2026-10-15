# PDCv2 helpers

One initializer for the PDCv2 acquisition scripts: a config loader, a register plan and a session object shared by the
TCR scan and the two DSUM modes. Settings live in YAML files.

## Install

The scripts live in `hostApps/python` next to `pdcv2_modules`. `setupHosts/setup.sh` creates the python environment from
`requirements.txt` here, or install it yourself:

    pip install -r requirements.txt

## Use

    python run_dsum_rad.py run.head_id=48 run.supply_V.keysight=49 run.run_folder=Co57_10152026
    python run_dsum_coincidence.py --run my_run.yaml
    python run_tcr.py tcr.meas_time_s=0.5 run.n_spad=64
    python run_dsum_rad.py --batch          # no prompts, no figure window
    python run_dsum_rad.py --show-config    # print the resolved config and exit

Positional arguments are overrides `section.key=value` (the value is parsed as YAML: `0xF`, `true`, `25.5`, text).
A key that does not exist is an error, so a typo never silently does nothing; `+section.key=value` adds a new key.

An entry script is these lines:

    cfg = build_config("dsum_rad", parse_args("dsum_rad"))
    with PdcSession(cfg) as session:
        DsumMode(session).execute()

## Config files

Everything you change is in `configs/`. Each key is in one file only. The files stack in this order and the later one wins:
hardware.yaml, then the mode file, then run.yaml, then the command line. The comments in each file say what each key is
in the form `Type - Description`.

| File | Holds | Edited |
| --- | --- | --- |
| `configs/hardware.yaml` | ssh host, controller clock, data folders, power supplies | when the bench changes |
| `configs/supplies/<model>.yaml` | commands one power supply model understands | when a supply model is added |
| `configs/modes/<mode>.yaml` | register values and Zynq commands of one mode | when the experiment changes |
| `configs/run.yaml` | head, supply voltages, measurement time, PDC mask, pixels, file name | between runs |
| command line | one-off overrides | per run |

Every run saves the fully resolved config next to its data (`*_config.yaml`).

### `hardware.yaml`

Defines the bench. Edit it when something on the bench changes, not between runs.

- `zynq` - SSH host name of the ZCU board (the `zcudev` entry that `setup.sh` adds to `~/.ssh/config`), the clock period and the delay for the PDC configuration signal.
- `paths` - Folder for user data and folder for the temporary HDF5 files. `null` uses `USER_DATA_DIR` and `HDF5_DATA_DIR` from the environment (`setup.sh` sets them), or `~/PDCv2-data`.
- `supplies` - One entry per power supply. Name them anything. They ramp up in the order listed and ramp down in reverse. The voltage each one ramps to is in run.yaml under the same name. Each entry has:
  - `model` - Which file in `configs/supplies` has the commands for this supply.
  - `connection` - How to reach it. `address` is the text given to pyvisa's `open_resource`: `ASRL<port>::INSTR` for serial (use the name in `/dev/serial/by-id` for the port), `USB0::<vendor>::<model>::<serial number>::0::INSTR` for USBTMC and `TCPIP0::<ip address>::INSTR` for LAN. Every other key in `connection` is given to `open_resource` as it is, like `baud_rate` for serial. A wrong option or address is an error when it connects, and the addresses pyvisa can see are printed. Use `python -c "import pyvisa; print(pyvisa.ResourceManager('@py').list_resources())"` to see them. The terminations are in the model file, not here. Two supplies cannot have the same address.
  - `step_V` and `step_delay_s` - Voltage step and time in seconds to wait between steps while ramping.
  - `slow_start_V` and `slow_step_V` - Below `slow_start_V` the ramp uses `slow_step_V` steps. Optional.
  - `ocp_A`, `ovp_V`, `ovp_margin_V` and `current_limit_A` - Protection numbers. Which ones a supply needs depends on its model file. `ovp_margin_V` sets the overvoltage protection at the target voltage plus the margin. `ovp_V` sets a fixed value instead.
  - `health_enable` - `true` runs the `health` check from the model file when it connects. `false` skips it, including `left_on` and `after_ok`. The `ensure_off` check and the protections are still done. Optional, `true` if left out.
  - `max_V` - Highest voltage run.yaml can ask for. The config check stops the run if it is higher.

### `supplies/<model>.yaml`

The commands one power supply model understands. There is one file per model (`bk.yaml`, `keysight.yaml`). Nothing in the python is specific to a model, so a new supply is a new file here.

- `terminations` - Characters added to everything sent (`write`) and removed from every reply (`read`).
- `idn` - Query for the identification of the supply. The reply is printed when it connects.
- `set_voltage` - Command that sets the voltage. `{v}` is replaced with the voltage. Any other `{name}` has to be a number in that supply's entry in hardware.yaml.
- `health` - Query that runs right after connecting. The reply is good if it has the text in `ok_contains` (one text or a list, any of them counts). If the reply has the text of a `left_on` entry, those commands turn off what a previous run left on. `left_on` is checked first. `after_ok` is sent when the reply is good.
- `ensure_off` - Optional. Query for the state of the output and the command that turns it off if it was left on.
- `protect` - Commands that set the protection limits. Sent while the output is off.
- `arm` - Commands sent before the ramp up. Turns the output on at 0 V.
- `disarm` - Commands sent after the ramp down. 0 V, output off and protections off.

To add a supply: connect to it with pyvisa and try the commands by hand, copy the closest model file and change the commands, add an entry in hardware.yaml with the new `model` name, and add its voltage to run.yaml. Put quotes around text that YAML can read as something else, like `"on"` or `"000001"`. The config check catches missing keys, a wrong `{name}` and values that are not text before it touches any hardware.

### `modes/<mode>.yaml`

One file per mode: `tcr` (total count rate of every SPAD), `dsum_rad` (digital sum with a radiation source) and `dsum_coincidence` (digital sum when several PDCs hit in the coincidence window). Each one is self contained, nothing is shared between them, so values repeated in the three files are on purpose. The mode is picked by the script you run. Each file has three sections:

- `behavior` - Choices that are not registers. `export_h5` creates an h5 file in the run folder (DSUM). `clear_hexread` runs clearHexRead() on startup. `power_supplies` ramps the supplies in hardware.yaml automatically, and false asks you to apply HV by hand. `per_pdc_pixel_off` uses the manual PDC masking in run.yaml. `allow_analog_only` allows analog only mode. `pdc_pix_dis_args` is added to the end of the `pdcPix --dis` command. `zpp_period_from_meas_time` (TCR only) sets the ZPP wait time to the measurement time.
- `pdc` - Register values written to every PDC: `time` (hold, recharge and flag times in ns), `PIXL`, `ANLG`, `STHL`, `FIFO`, `OUTD`, `OUTF`, `TRGC` and `OUTC`. The names are the register names.
- `controller` - Register values of the Controller and the commands run on the Zynq. `packet` is what data is sent, `fsm` is the acquisition timing (samples, trigger mode, timeout, end, tx), `interfaces` and `coincidence` are the interface and coincidence registers, and `apps` are the Zynq commands like streamManager, auxOut and auxIn.

### `run.yaml`

Edit it between runs. It is the same for every mode.

- `run` - `run_folder` is the folder this run is saved in, made inside `hardware.paths.user_data_dir` (for example `tcr_10152026`). It is required, and the run stops with a config error when it is empty. Everything a run writes goes in this folder. `head_id` is the head used. `supply_V` is the voltage for each supply in hardware.yaml (same names). `spad_supply` is the supply that biases the SPADs. Its voltage is used in the file name, and empty means no voltage in the file name. `name` is added to the end of the file name. `meas_time_s` is the time of a DSUM measurement. `pdc_enable` is which PDCs to enable (hex mask, `0xF` is all). `n_spad` is the number of SPADs per PDC. `analog_only`, `save_plot` and `batch_mode` turn on analog only mode, save the output plot and remove user input.
- `pixels` - Which SPADs are on for DSUM. `source: tcr_file` finds screamers from the TCR file in `tcr_file` (a full path str) and `source: all` turns off screamer masking. `screamer` picks how to find screamers: `method` is constant, average, percent, medianFactor or medianToMin, and `threshold`, `percent` and `factor` are the numbers the method uses. `mask` is the area that is on (`cx`, `cy`, `width`, `height`, and `checker` for a checkerboard). `show_mask` shows the mask at the start. `per_pdc_off` are areas to turn off in each PDC when `per_pdc_pixel_off` is true.
- `tcr` - `meas_time_s` is the time per TCR measurement. `screamer` is the same as above but for TCR.
- `dsum` - Options for the dsum module of hexRead. `data_type` is all, NZ, NZKF, dt or max and `bin_idx_mode` is time, continuous or frame.

Use `--run FILE` to run with a different run file, so you can keep one for each setup.

### Where data goes

`hardware.paths.user_data_dir` is the parent of all data (empty uses the `USER_DATA_DIR` environment variable). Each run writes into its own folder inside it, named by `run.run_folder`:

    <user_data_dir>/<run_folder>/
        <date>_<mode>_...csv                  DSUM data, or <date>_TCR_...csv for a TCR scan
        <same name>.h5                        DSUM with behavior.export_h5
        <same name>.txt, _config.yaml         pixel enabling log and the config used
        <same name>_pixelMap_<n>.png          the mask of each PDC
        PNG/                                  TCR plots

A TCR scan reads and deletes one HDF5 file per SPAD. Those go in `.tmp_h5/` inside the run folder, which is removed when the scan finishes. Use the same `run_folder` for a TCR scan and the DSUM runs that use it

### Command line

Any key can be changed for one run with `section.key=value`, like `run.head_id=48` or `run.supply_V.keysight=49`. A key that does not exist is an error, so a typo never silently does nothing. `+section.key=value` adds a new key. `--show-config` prints the full resolved config and exits.

## Layout

    run_tcr.py  run_dsum_rad.py  run_dsum_coincidence.py   entry scripts
    configs/                                               hardware.yaml, run.yaml, modes/*.yaml
    configs/supplies/                                      command dialect of each supply model (bk.yaml, keysight.yaml); hardware.yaml picks one with model:
    pdcv2_helpers/registers.py                             register definitions: name, address, bit fields (14 PDC + 67 controller registers)
    pdcv2_helpers/plan.py                                  config -> ordered register writes, in named groups (packet, fsm, pdc, pdc_final, ...)
    pdcv2_helpers/config.py                                load, merge, override, validate
    pdcv2_helpers/session.py                               PdcSession: connection + the shared init sequence
    pdcv2_helpers/pixels.py                                which SPADs to enable (TCR file -> screamer threshold -> mask -> pixel registers)
    pdcv2_helpers/power.py                                 PowerSupply: find, connect, health check, protections, ramp up/down. Driven by config
    pdcv2_helpers/paths.py                                 data folders and file names
    pdcv2_helpers/modes/                                   Mode base class, DsumMode, TcrMode, TcrPlotter
