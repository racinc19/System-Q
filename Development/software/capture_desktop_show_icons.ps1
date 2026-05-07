# Win+D toggle show desktop briefly, capture, toggle back.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class DesktopToggle {
 [DllImport("user32.dll")]
 public static extern void keybd_event(byte vk, byte scan, uint dwFlags, UIntPtr dwExtraInfo);
 public const uint KEYEVENTF_KEYUP = 2;
 const byte VK_LWIN = 0x5B;
 const byte VK_D = 0x44;
 public static void SendWinD(){
  keybd_event(VK_LWIN, 0, 0, UIntPtr.Zero);
  keybd_event(VK_D, 0, 0, UIntPtr.Zero);
  keybd_event(VK_D, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
  keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
 }
}
'@

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[DesktopToggle]::SendWinD()
Start-Sleep -Milliseconds 800

$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $b.Size)
$p = Join-Path $PSScriptRoot "agent_desktop_icons_visible.png"
$bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
Write-Host $p

[DesktopToggle]::SendWinD()
Start-Sleep -Milliseconds 600
