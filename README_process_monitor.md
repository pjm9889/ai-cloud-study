# Process Top 20 CSV Monitor

`process_monitor.ps1` records the 20 processes using the most memory.
Each run appends 20 new rows to `output\process_top20.csv`.

## Recorded information

- Capture time and computer name
- Manufacturer, model, Windows version, CPU, total RAM, and uptime
- Process rank, name, ID, memory, accumulated CPU time, threads, handles, and start time

`CPU_TotalSeconds` is the accumulated processor time since the process started. It is not the live CPU percentage shown in Task Manager.

## First run

1. Put `process_monitor.ps1` in the folder you want to use.
2. Open that folder in File Explorer.
3. Click the address bar, type `powershell`, and press Enter.
4. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\process_monitor.ps1
```

The script automatically creates the `output` folder and the CSV file.

## Add another snapshot

Run the same command again:

```powershell
powershell -ExecutionPolicy Bypass -File .\process_monitor.ps1
```

Do not open the CSV in Excel while running the script. Excel may lock the file and prevent appending.

## Check the result

```powershell
Invoke-Item .\output\process_top20.csv
```

The first run creates the header and 20 rows. Every later run adds another 20 rows beneath them.
