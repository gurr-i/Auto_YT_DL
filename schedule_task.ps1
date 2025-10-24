$Action = New-ScheduledTaskAction -Execute "C:\Python313\python.exe" -Argument '-u "F:\Python_Projects\Auto_YT_DL\auto_yt_live.py"' -WorkingDirectory "F:\Python_Projects\Auto_YT_DL"
$Trigger = New-ScheduledTaskTrigger -Daily -At 8:30AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3

# Task name and description
$TaskName = "YouTubeLiveDownloader"
$Description = "Runs YouTube Live downloader script daily at 9:30 AM"

# Register the scheduled task (needs to be run as administrator)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description $Description -Force