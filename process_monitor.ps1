# Save the 20 processes using the most memory and append them to a CSV file.

$ErrorActionPreference = "Stop"

try {
    $outputDir = Join-Path $PSScriptRoot "output"
    $csvPath = Join-Path $outputDir "process_top20.csv"
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    $capturedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $computer = Get-CimInstance Win32_ComputerSystem
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $uptimeHours = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 2)

    $rows = Get-Process |
        Sort-Object WorkingSet64 -Descending |
        Select-Object -First 20 |
        ForEach-Object {
            $startTime = $null
            try { $startTime = $_.StartTime.ToString("yyyy-MM-dd HH:mm:ss") } catch {}

            [PSCustomObject]@{
                CapturedAt       = $capturedAt
                ComputerName     = $env:COMPUTERNAME
                Manufacturer     = $computer.Manufacturer
                Model            = $computer.Model
                OS               = $os.Caption
                CPU              = $cpu.Name.Trim()
                TotalRAM_GB      = [math]::Round($computer.TotalPhysicalMemory / 1GB, 2)
                Uptime_Hours     = $uptimeHours
                RankByMemory     = 0
                ProcessName      = $_.ProcessName
                ProcessId        = $_.Id
                Memory_MB        = [math]::Round($_.WorkingSet64 / 1MB, 2)
                CPU_TotalSeconds = if ($null -eq $_.CPU) { $null } else { [math]::Round($_.CPU, 2) }
                Threads          = $_.Threads.Count
                Handles          = $_.HandleCount
                StartTime        = $startTime
            }
        }

    for ($index = 0; $index -lt $rows.Count; $index++) {
        $rows[$index].RankByMemory = $index + 1
    }

    if (Test-Path $csvPath) {
        $rows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8 -Append
    }
    else {
        $rows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
    }

    Write-Host "Saved 20 rows: $csvPath" -ForegroundColor Green
}
catch {
    Write-Error "Failed to save process information: $($_.Exception.Message)"
    exit 1
}
