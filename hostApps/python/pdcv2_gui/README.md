# PDCv2 control GUI

A desktop front end for the run scripts. It edits the config files, queues runs and shows their output. The scripts and
the config format are unchanged: every job is a normal `python run_<mode>.py ...` command.

## Start

    python run_gui.py [--config-dir DIR]

Run it from the python environment of the scripts (`~/venv_pdcv2`, packages from `requirements.txt`), or set the
interpreter in Settings.

## Pages

**Main** has the pinned settings (left), the queue (right) and the log (bottom). **Configs** has one editor per file in
`configs/` (run, hardware, every mode, every supply) with a form view and a raw YAML view. The comments in the files are
shown as the descriptions and tooltips, and are kept when a file is saved.

### Pinned settings

Tick *Main* next to any setting in the Configs tab to show it on the main page. Right click a pinned setting to move or
unpin it. Pins live in `configs/gui.yaml`. Settings of a mode file only show while that mode is selected.

### Working copy and jobs

Edits are made on an in-memory copy of the files. *Save configs* writes them to disk. *Add current settings* takes a
snapshot of the working copy as a full configs folder and queues `python run_<mode>.py --batch --config-dir <snapshot>`,
so a job runs with the values that were on screen when it was queued, whatever is edited or saved afterwards. Four
jobs with four head IDs can be queued without saving anything. *Load settings* puts a job's values back on screen.

Before a job is queued the script's own `--show-config` runs on the snapshot, so config errors show up now and not an
hour into the queue.

### Queue

Jobs run one after another, because the bench is one shared resource. Jobs can be reordered, switched off with the
checkbox, duplicated, re-queued and removed. *On failure* (Settings) either stops the queue or continues with the next
job. *Pause after current* finishes the running job and waits.

- **Add sweep** queues one job per value, or per combination of values of two settings, with the run folder built from a
  template. It replaces hand-written loops like `run_tcr_batch.py`.
- **Add script job** queues any script of this folder with arguments.
- **Stop** sends Ctrl-C to the script, which ramps the supplies down before it exits, and stops the queue. *Force kill*
  is a separate, confirmed action because it skips the ramp down.

### Log

The log shows every job and the GUI messages. Error lines (including whole tracebacks) are red and warnings are yellow;
the filters show all lines, warnings and errors, or errors only, for one job or all, with a text filter. tqdm bars
drive the progress bar. A line that waits without a newline is treated as a prompt and the reply box at the bottom
sends text to the running job. Each job's output is also saved in `~/.pdcv2_gui/logs/<job id>.log`.

## Layout

    run_gui.py                     entry script
    pdcv2_gui/yamlio.py            comment-preserving YAML, type hints from the `Type - Description` comments
    pdcv2_gui/workspace.py         working copy of the files, pins, snapshots, cheap on-screen checks
    pdcv2_gui/jobs.py              Job, JobQueue (QProcess), line classification, config preflight
    pdcv2_gui/widgets.py           value editors, quick settings, file editor, log view, queue table
    pdcv2_gui/dialogs.py           sweep, script job and settings dialogs
    pdcv2_gui/main_window.py       main window

State outside the repo is in `~/.pdcv2_gui/` (`settings.json`, `queue.json`, `jobs/<id>/configs/` snapshots, `logs/`).
Set `PDCV2_GUI_HOME` to move it.
