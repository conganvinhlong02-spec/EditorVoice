param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$bitmap = New-Object System.Drawing.Bitmap 256, 256
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $background = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(18, 19, 28))
    $graphics.FillEllipse($background, 6, 6, 244, 244)
    $background.Dispose()

    $ring = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(130, 112, 89, 255)), 5
    $graphics.DrawEllipse($ring, 10, 10, 236, 236)
    $ring.Dispose()

    $bars = @(58, 84, 124, 164, 112, 74, 102)
    for ($index = 0; $index -lt $bars.Count; $index++) {
        $x = 57 + ($index * 24)
        $height = $bars[$index]
        $startY = 128 - [int]($height / 2)
        $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(216, 255, 99)), 13
        $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $graphics.DrawLine($pen, $x, $startY, $x, $startY + $height)
        $pen.Dispose()
    }

    $accent = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(126, 101, 255))
    $graphics.FillEllipse($accent, 109, 109, 38, 38)
    $accent.Dispose()

    $pngStream = New-Object System.IO.MemoryStream
    try {
        $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $pngBytes = $pngStream.ToArray()
    }
    finally {
        $pngStream.Dispose()
    }

    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $output = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    try {
        $writer = New-Object System.IO.BinaryWriter $output
        try {
            $writer.Write([UInt16]0)
            $writer.Write([UInt16]1)
            $writer.Write([UInt16]1)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([UInt16]1)
            $writer.Write([UInt16]32)
            $writer.Write([UInt32]$pngBytes.Length)
            $writer.Write([UInt32]22)
            $writer.Write($pngBytes)
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $output.Dispose()
    }
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
