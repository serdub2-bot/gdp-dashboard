# find-db.ps1 — где на самом деле лежит база FM2008
# Запускается из find-db.bat, отдельно запускать не обязательно.

$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $PSScriptRoot 'FM_found_databases.txt'

$known = @{
  '5bcb16c428575555b1d47174a48a980b' = 'ОРИГИНАЛ  client_db.dat (ваша база, НЕ пропатчена)'
  'be8ecb770612094164b2820a4b26fc7d' = 'ОРИГИНАЛ  server_db.dat'
  '3f407fe63c777b499e09a1765006352f' = 'ОРИГИНАЛ  lang_db.dat'
  '927dc5a27429b66b2996bf101183b1eda383f6bc65732015f82ed005dbf16709' = 'ПАТЧ      client_db.dat (наш)'
  '3a383cc8cd3145a72a38986f86b02194825d66eaeeaad0e1ac8dc13bc117fd3e' = 'ПАТЧ      server_db.dat (наш)'
  'e96f05c6fa2a783384009760f04ff964df36ec23ce4737e4f3115b483931e221' = 'ПАТЧ      lang_db.dat (наш, с меткой РОССИЯ)'
}

$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('Отчёт: поиск базы Football Manager 2008')
$rows.Add('Дата: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm'))
$rows.Add('')

$drives = (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Za-z]:' }).Root
Write-Host ''
Write-Host 'Ищу client_db.dat на дисках:' $drives -join ' '
Write-Host ''

$found = 0
foreach ($d in $drives) {
  Get-ChildItem -Path $d -Filter 'client_db.dat' -Recurse -File | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    $tag = $known[$hash]
    if (-not $tag) {
      if ($hash.StartsWith('927dc5a27429b66b')) { $tag = 'ПАТЧ      client_db.dat (наш)' }
      elseif ($hash.StartsWith('5bcb16c428575555')) { $tag = 'ОРИГИНАЛ  client_db.dat (ваша база, НЕ пропатчена)' }
      else { $tag = 'НЕИЗВЕСТНЫЙ файл (другая версия или чужая правка)' }
    }
    $script:found++
    $rows.Add(('{0}  {1}  {2}' -f $tag, $hash.Substring(0, 16), $_.FullName))
    Write-Host ('  ' + $tag)
    Write-Host ('    ' + $_.FullName)
  }
}
if ($found -eq 0) {
  $rows.Add('client_db.dat не найден вообще. Игра не установлена на этих дисках?')
  Write-Host '  client_db.dat не найден.'
}

$rows.Add('')
$rows.Add('--- папки базы (в них должен лежать 802.xml) ---')
foreach ($d in $drives) {
  Get-ChildItem -Path $d -Directory -Filter '802.xml' -Recurse -File | ForEach-Object {
    $rows.Add('  ' + $_.FullName)
    Write-Host ('  папка базы: ' + $_.FullName)
  }
}

$rows.Add('')
$rows.Add('--- папки rus2 (наш набор) ---')
$rus = 0
foreach ($d in $drives) {
  Get-ChildItem -Path $d -Directory -Filter 'rus2' -Recurse | ForEach-Object {
    if (Test-Path (Join-Path $_.FullName 'rus2.xml')) {
      $rus++
      $rows.Add('  ' + $_.FullName)
      Write-Host ('  наш набор: ' + $_.FullName)
    }
  }
}
if ($rus -eq 0) { $rows.Add('  не найдено — архив не распакован в data\db') }

$rows.Add('')
$rows.Add('--- кэш игры (его надо удалять после подмены файлов) ---')
$cache = Join-Path $env:USERPROFILE 'Documents\Sports Interactive\Football Manager 2008\cache'
if (Test-Path $cache) {
  $rows.Add('  есть: ' + $cache)
  Write-Host ('  кэш: ' + $cache)
} else {
  $rows.Add('  нет (хорошо)')
}

$rows.Add('')
$rows.Add('--- Steam ---')
foreach ($k in @('HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam')) {
  if (Test-Path $k) {
    $p = (Get-ItemProperty $k).InstallPath
    $rows.Add('  Steam: ' + $p)
    Write-Host ('  Steam: ' + $p)
  }
}

$rows.Add('')
$rows.Add('--- VirtualStore (Windows прячет сюда правки Program Files) ---')
$vs = Join-Path $env:LOCALAPPDATA 'VirtualStore'
if (Test-Path $vs) {
  $rows.Add('  есть: ' + $vs)
  Get-ChildItem $vs -Recurse -Filter 'client_db*.dat' | ForEach-Object { $rows.Add('    ' + $_.FullName) }
} else {
  $rows.Add('  нет')
}

$rows | Set-Content -Path $out -Encoding UTF8
Write-Host ''
Write-Host ('Отчёт сохранён: ' + $out)
