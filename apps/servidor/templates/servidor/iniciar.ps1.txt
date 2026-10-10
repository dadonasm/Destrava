# Destrava! - iniciar sem pendrive (Windows), pelo servidor da loja.
# Uso, no PowerShell:   irm __SERVIDOR__/iniciar.ps1 | iex
# Baixa o programa e um Python fixo para uma pasta temporaria, roda, e APAGA tudo ao terminar.
# Fichas, historicos e termos ficam no servidor, nao neste computador.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Servidor = '__SERVIDOR__'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$adm = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $adm) {
  Write-Host 'Pedindo permissao de administrador...'
  Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', "irm '$Servidor/iniciar.ps1' | iex"
  return
}

# sobras de execucoes anteriores fechadas a forca
Get-ChildItem $env:TEMP -Directory -Filter 'Destrava-*' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'Destrava! - D&D Technology' -ForegroundColor Yellow
$sec = Read-Host 'Chave do tecnico' -AsSecureString
$chave = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
$h = @{ Authorization = "Bearer $chave" }
try {
  $info = Invoke-RestMethod "$Servidor/pacote/info" -Headers $h -UseBasicParsing
} catch {
  Write-Host 'Nao consegui entrar: chave errada ou servidor fora do ar.' -ForegroundColor Red
  return
}

$pasta = Join-Path $env:TEMP ('Destrava-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory $pasta | Out-Null
try {
  function Baixar($url, $arq, $sha) {
    Invoke-WebRequest $url -Headers $h -OutFile $arq -UseBasicParsing
    if ((Get-FileHash $arq -Algorithm SHA256).Hash.ToLower() -ne $sha) { throw "Arquivo corrompido no download: $url" }
  }
  Write-Host "Baixando o Destrava! $($info.versao)..."
  Baixar "$Servidor/pacote/Destrava.zip" "$pasta\Destrava.zip" $info.sha256
  Expand-Archive "$pasta\Destrava.zip" $pasta

  $py = $null; $pyArgs = @()
  $rt = $info.runtimes.'windows-amd64'
  if ($rt) {
    Write-Host "Baixando o Python $($rt.python)..."
    Baixar "$Servidor/runtime/windows-amd64" "$pasta\python.zip" $rt.sha256
    Expand-Archive "$pasta\python.zip" "$pasta\python"
    $py = "$pasta\python\python.exe"
  } elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $py = 'py'; $pyArgs = @('-3')
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = 'python'
  } else {
    throw 'O servidor ainda nao tem o Python para Windows (rode baixar_runtimes.py no servidor).'
  }

  $env:DESTRAVA_CHAVE = $chave
  & $py @pyArgs "$pasta\Destrava\dd_backup.py" --servidor $Servidor
} finally {
  Remove-Item Env:DESTRAVA_CHAVE -ErrorAction SilentlyContinue
  $chave = $null
  Set-Location $env:TEMP
  Start-Sleep -Seconds 1
  Remove-Item $pasta -Recurse -Force -ErrorAction SilentlyContinue
  if (Test-Path $pasta) { Write-Host "Nao consegui apagar $pasta (feche o programa e apague a pasta)." -ForegroundColor Yellow }
  else { Write-Host 'Pronto. Os arquivos temporarios do Destrava! foram apagados deste computador.' -ForegroundColor Green }
}
