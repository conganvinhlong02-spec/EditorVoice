using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class EditorVoiceInstaller
{
    private const string ProductName = "EditorVoice";
    private const string ProductVersion = "1.2.31";
    private const string PayloadResource = "EditorVoice.Package.zip";
    private const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\EditorVoice";

    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length > 0 && string.Equals(args[0], "/uninstall", StringComparison.OrdinalIgnoreCase))
        {
            Uninstall();
            return;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm());
    }

    private static string DefaultInstallPath()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", ProductName);
    }

    private static void Install(string installPath, Action<string> report)
    {
        installPath = Path.GetFullPath(installPath);
        StopRunningEditorVoice(installPath, report);
        Directory.CreateDirectory(installPath);
        report("Đang chép ứng dụng...");

        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadResource))
        {
            if (stream == null) throw new InvalidOperationException("Không tìm thấy dữ liệu cài đặt.");
            using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string destination = Path.GetFullPath(Path.Combine(installPath, entry.FullName));
                    if (!destination.StartsWith(installPath.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                        && !string.Equals(destination, installPath, StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("Gói cài đặt chứa đường dẫn không hợp lệ.");
                    }
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(destination);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(destination));
                    try
                    {
                        entry.ExtractToFile(destination, true);
                    }
                    catch (IOException error)
                    {
                        throw new IOException(
                            "EditorVoice vẫn đang được Windows sử dụng. Hãy chờ vài giây rồi bấm Cài đặt lại.",
                            error
                        );
                    }
                }
            }
        }

        string launcher = Path.Combine(installPath, "EditorVoice.exe");
        if (!File.Exists(launcher)) throw new FileNotFoundException("Không tìm thấy file chạy ứng dụng sau khi cài đặt.", launcher);

        report("Đang tạo shortcut...");
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        string startMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", ProductName);
        Directory.CreateDirectory(startMenu);
        CreateShortcut(Path.Combine(desktop, ProductName + ".lnk"), launcher, installPath, "Mở EditorVoice");
        CreateShortcut(Path.Combine(startMenu, ProductName + ".lnk"), launcher, installPath, "Mở EditorVoice");

        string uninstallExe = Path.Combine(installPath, "Uninstall EditorVoice.exe");
        File.Copy(Application.ExecutablePath, uninstallExe, true);
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallKey))
        {
            key.SetValue("DisplayName", ProductName);
            key.SetValue("DisplayVersion", ProductVersion);
            key.SetValue("Publisher", "EditorVoice");
            key.SetValue("InstallLocation", installPath);
            key.SetValue("DisplayIcon", launcher);
            key.SetValue("NoModify", 1, RegistryValueKind.DWord);
            key.SetValue("UninstallString", "\"" + uninstallExe + "\" /uninstall");
        }
    }

    private static void StopRunningEditorVoice(string installPath, Action<string> report)
    {
        string launcher = Path.Combine(installPath, "EditorVoice.exe");
        string python = Path.Combine(installPath, "runtime", "pythonw.exe");
        bool foundRunningApp = false;

        foreach (Process process in Process.GetProcessesByName("EditorVoice"))
        {
            if (!ProcessUsesPath(process, launcher)) continue;
            foundRunningApp = true;
            StopProcessForUpdate(process);
        }
        foreach (Process process in Process.GetProcessesByName("pythonw"))
        {
            if (!ProcessUsesPath(process, python)) continue;
            foundRunningApp = true;
            StopProcessForUpdate(process);
        }

        if (foundRunningApp)
        {
            report("Đang đóng EditorVoice để cập nhật...");
            Thread.Sleep(700);
        }
    }

    private static bool ProcessUsesPath(Process process, string expectedPath)
    {
        try
        {
            return string.Equals(
                Path.GetFullPath(process.MainModule.FileName),
                Path.GetFullPath(expectedPath),
                StringComparison.OrdinalIgnoreCase
            );
        }
        catch
        {
            return false;
        }
    }

    private static void StopProcessForUpdate(Process process)
    {
        try
        {
            if (!process.HasExited) process.Kill();
            process.WaitForExit(5000);
        }
        finally
        {
            process.Dispose();
        }
    }

    private static void CreateShortcut(string shortcutPath, string targetPath, string workingDirectory, string description)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(shellType);
        object shortcut = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcutPath });
        Type shortcutType = shortcut.GetType();
        shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetPath });
        shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDirectory });
        shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
        shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { targetPath + ",0" });
        shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
    }

    private static void Uninstall()
    {
        string installPath = Path.GetDirectoryName(Application.ExecutablePath);
        DialogResult confirm = MessageBox.Show("Gỡ EditorVoice khỏi máy này? Lịch sử giọng và giọng clone đã lưu sẽ được giữ lại.", ProductName, MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (confirm != DialogResult.Yes) return;

        string desktopShortcut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), ProductName + ".lnk");
        string startMenuFolder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", ProductName);
        TryDeleteFile(desktopShortcut);
        TryDeleteDirectory(startMenuFolder);
        Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false);

        string cleanupScript = Path.Combine(Path.GetTempPath(), "remove-editorvoice-" + Guid.NewGuid().ToString("N") + ".cmd");
        File.WriteAllText(cleanupScript,
            "@echo off\r\n" +
            "ping 127.0.0.1 -n 3 > nul\r\n" +
            "rmdir /s /q \"" + installPath + "\"\r\n" +
            "del /q \"%~f0\"\r\n");
        Process.Start(new ProcessStartInfo { FileName = cleanupScript, WindowStyle = ProcessWindowStyle.Hidden, CreateNoWindow = true, UseShellExecute = true });
        MessageBox.Show("EditorVoice đã được gỡ. Cửa sổ này sẽ đóng lại.", ProductName, MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static void TryDeleteFile(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    private static void TryDeleteDirectory(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, true); } catch { }
    }

    private sealed class InstallerForm : Form
    {
        private readonly TextBox location = new TextBox();
        private readonly Button install = new Button();
        private readonly Label status = new Label();

        internal InstallerForm()
        {
            Text = ProductName + " Setup";
            ClientSize = new Size(560, 310);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(18, 19, 24);
            ForeColor = Color.FromArgb(246, 245, 240);

            Label title = new Label { Text = "Cài đặt EditorVoice", Left = 32, Top = 30, Width = 480, Height = 36, Font = new Font("Segoe UI", 18, FontStyle.Bold), ForeColor = Color.FromArgb(216, 255, 99) };
            Label description = new Label { Text = "Ứng dụng tạo giọng AI tiếng Việt chạy trực tiếp trên máy.", Left = 34, Top = 75, Width = 480, Height = 30, Font = new Font("Segoe UI", 10), ForeColor = Color.FromArgb(200, 202, 211) };
            Label target = new Label { Text = "Cài đặt vào", Left = 34, Top = 124, Width = 180, Height = 22, Font = new Font("Segoe UI", 10, FontStyle.Bold) };
            location.SetBounds(34, 150, 400, 34);
            location.Text = DefaultInstallPath();
            location.Font = new Font("Segoe UI", 10);
            Button browse = new Button { Text = "Chọn...", Left = 444, Top = 150, Width = 82, Height = 34, FlatStyle = FlatStyle.Flat };
            browse.Click += delegate
            {
                using (FolderBrowserDialog dialog = new FolderBrowserDialog { SelectedPath = location.Text, Description = "Chọn thư mục cài đặt" })
                {
                    if (dialog.ShowDialog(this) == DialogResult.OK) location.Text = dialog.SelectedPath;
                }
            };
            install.Text = "Cài đặt";
            install.SetBounds(34, 216, 492, 44);
            install.FlatStyle = FlatStyle.Flat;
            install.BackColor = Color.FromArgb(216, 255, 99);
            install.ForeColor = Color.FromArgb(18, 19, 24);
            install.Font = new Font("Segoe UI", 11, FontStyle.Bold);
            install.Click += InstallClick;
            status.SetBounds(34, 270, 492, 22);
            status.Font = new Font("Segoe UI", 9);
            status.ForeColor = Color.FromArgb(173, 176, 187);
            status.Text = "Sẽ tạo shortcut trên Desktop và Start Menu.";

            Controls.AddRange(new Control[] { title, description, target, location, browse, install, status });
        }

        private void InstallClick(object sender, EventArgs e)
        {
            string target = location.Text.Trim();
            if (string.IsNullOrWhiteSpace(target))
            {
                MessageBox.Show("Hãy chọn thư mục cài đặt.", ProductName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try
            {
                install.Enabled = false;
                location.Enabled = false;
                Cursor = Cursors.WaitCursor;
                Install(target, message => { status.Text = message; status.Refresh(); });
                status.Text = "Cài đặt hoàn tất.";
                DialogResult launch = MessageBox.Show("Cài đặt hoàn tất. Mở EditorVoice ngay bây giờ?", ProductName, MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (launch == DialogResult.Yes) Process.Start(Path.Combine(Path.GetFullPath(target), "EditorVoice.exe"));
                Close();
            }
            catch (Exception error)
            {
                MessageBox.Show("Không thể cài đặt ứng dụng.\n\n" + error.Message, ProductName, MessageBoxButtons.OK, MessageBoxIcon.Error);
                install.Enabled = true;
                location.Enabled = true;
                status.Text = "Cài đặt chưa hoàn tất.";
            }
            finally
            {
                Cursor = Cursors.Default;
            }
        }
    }
}
