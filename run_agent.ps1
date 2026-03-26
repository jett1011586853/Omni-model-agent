param(
    [string]$Prompt,
    [string[]]$Image,
    [string[]]$ImageUrl
)

$condaHook = conda shell.powershell hook
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize conda shell hook."
}

$condaHook | Out-String | Invoke-Expression
conda activate homework

if ($Prompt) {
    $arguments = @("agent.py", "--prompt", $Prompt)
    foreach ($path in ($Image | Where-Object { $_ })) {
        $arguments += @("--image", $path)
    }
    foreach ($url in ($ImageUrl | Where-Object { $_ })) {
        $arguments += @("--image-url", $url)
    }
    python @arguments
} else {
    python agent.py
}
