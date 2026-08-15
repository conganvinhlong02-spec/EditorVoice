using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace EditorVoiceDesktop
{
    internal static class Program
    {
        internal static Process ServerProcess;
        private static Mutex _singleInstance;
        // EditorVN release policy: every future package must update the fixed
        // expiry, product version and visible release code together unless the
        // owner explicitly changes this policy.
        internal static readonly DateTime ReleaseExpiresAt = new DateTime(2026, 8, 30, 0, 0, 0, DateTimeKind.Local);
#if EDITORVOICE_UNLIMITED
        internal const bool UnlimitedRelease = true;
#else
        internal const bool UnlimitedRelease = false;
#endif
        internal const string ProductVersion = "1.2.30";
        internal const string ReleaseCode = "30082600";
        internal const string UpdateUrl = "https://EditorVN.com";

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        private static extern int SetCurrentProcessExplicitAppUserModelID(string appID);

        [STAThread]
        private static void Main(string[] args)
        {
            try
            {
                // Associate the native window with EditorVoice so Windows keeps our
                // executable icon in the taskbar instead of showing a browser icon.
                SetCurrentProcessExplicitAppUserModelID("EditorVoice.Desktop");

                bool createdNew;
                _singleInstance = new Mutex(true, @"Local\EditorVoiceDesktop", out createdNew);
                if (!createdNew)
                {
                    MessageBox.Show(
                        "EditorVoice đang chạy. Hãy kiểm tra cửa sổ ứng dụng đang mở.",
                        "EditorVoice",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information
                    );
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                bool previewExpired = args != null && Array.Exists(
                    args,
                    delegate(string value) { return String.Equals(value, "/preview-expired", StringComparison.OrdinalIgnoreCase); }
                );
                bool releaseExpired = false;
#if !EDITORVOICE_UNLIMITED
                releaseExpired = DateTime.Now >= ReleaseExpiresAt;
#endif
                if (previewExpired || releaseExpired)
                {
                    using (ExpiredReleaseForm form = new ExpiredReleaseForm())
                    {
                        Application.Run(form);
                    }
                }
                else
                {
                    using (EditorVoiceForm form = new EditorVoiceForm())
                    {
                        Application.Run(form);
                    }
                }

                StopProcess(ServerProcess);
                _singleInstance.ReleaseMutex();
            }
            catch (Exception error)
            {
                Log(error.ToString());
                MessageBox.Show(
                    error.Message,
                    "Không thể mở EditorVoice",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
        }

        internal static void Log(string message)
        {
            try
            {
                string directory = Path.Combine(GetDataRoot(), "logs");
                Directory.CreateDirectory(directory);
                File.AppendAllText(
                    Path.Combine(directory, "launcher.log"),
                    DateTime.Now.ToString("s") + " " + message + Environment.NewLine
                );
            }
            catch { }
        }

        internal static string GetDataRoot()
        {
            string customRoot = Environment.GetEnvironmentVariable("VIENEU_APP_DATA_DIR");
            if (!String.IsNullOrEmpty(customRoot)) return Path.GetFullPath(customRoot);
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "EditorVoice"
            );
        }

        internal static void StopProcess(Process process)
        {
            if (process == null) return;
            try
            {
                if (!process.HasExited) process.Kill();
            }
            catch { }
            finally
            {
                process.Dispose();
            }
        }
    }

    internal sealed class ExpiredReleaseForm : Form
    {
        internal ExpiredReleaseForm()
        {
            Text = "EditorVoice";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(680, 410);
            MinimumSize = new Size(680, 410);
            MaximumSize = new Size(680, 410);
            MaximizeBox = false;
            BackColor = Color.FromArgb(247, 246, 241);
            Font = new Font("Segoe UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            Panel accent = new Panel();
            accent.Dock = DockStyle.Top;
            accent.Height = 8;
            accent.BackColor = Color.FromArgb(216, 255, 99);
            Controls.Add(accent);

            Label badge = new Label();
            badge.AutoSize = false;
            badge.Location = new Point(48, 48);
            badge.Size = new Size(214, 30);
            badge.BackColor = Color.FromArgb(235, 229, 255);
            badge.ForeColor = Color.FromArgb(92, 73, 202);
            badge.TextAlign = ContentAlignment.MiddleCenter;
            badge.Font = new Font("Segoe UI", 9F, FontStyle.Bold, GraphicsUnit.Point);
            badge.Text = "PHIÊN BẢN ĐÃ HẾT HẠN";
            Controls.Add(badge);

            Label title = new Label();
            title.AutoSize = false;
            title.Location = new Point(48, 98);
            title.Size = new Size(584, 55);
            title.ForeColor = Color.FromArgb(17, 18, 23);
            title.Font = new Font("Segoe UI", 24F, FontStyle.Bold, GraphicsUnit.Point);
            title.Text = "Cần cập nhật EditorVoice";
            Controls.Add(title);

            Label message = new Label();
            message.AutoSize = false;
            message.Location = new Point(50, 166);
            message.Size = new Size(580, 78);
            message.ForeColor = Color.FromArgb(92, 94, 104);
            message.Font = new Font("Segoe UI", 11F, FontStyle.Regular, GraphicsUnit.Point);
            message.Text = "Phiên bản EditorVoice này đã hết thời hạn sử dụng.\r\nVui lòng truy cập EditorVN.com để tải và cài đặt phiên bản mới nhất.";
            Controls.Add(message);

            Label expiry = new Label();
            expiry.AutoSize = false;
            expiry.Location = new Point(50, 250);
            expiry.Size = new Size(580, 30);
            expiry.ForeColor = Color.FromArgb(108, 112, 124);
            expiry.Font = new Font("Segoe UI", 9F, FontStyle.Regular, GraphicsUnit.Point);
            expiry.Text = "Phiên bản " + Program.ProductVersion + " · Mã " + Program.ReleaseCode;
            Controls.Add(expiry);

            Button update = new Button();
            update.Location = new Point(50, 312);
            update.Size = new Size(390, 52);
            update.FlatStyle = FlatStyle.Flat;
            update.FlatAppearance.BorderSize = 0;
            update.BackColor = Color.FromArgb(216, 255, 99);
            update.ForeColor = Color.FromArgb(17, 18, 23);
            update.Cursor = Cursors.Hand;
            update.Font = new Font("Segoe UI", 11F, FontStyle.Bold, GraphicsUnit.Point);
            update.Text = "Truy cập EditorVN.com";
            update.Click += delegate
            {
                try
                {
                    ProcessStartInfo info = new ProcessStartInfo(Program.UpdateUrl);
                    info.UseShellExecute = true;
                    Process.Start(info);
                }
                catch
                {
                    Clipboard.SetText(Program.UpdateUrl);
                    MessageBox.Show("Đã sao chép địa chỉ EditorVN.com.", "EditorVoice", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
            };
            Controls.Add(update);

            Button close = new Button();
            close.Location = new Point(452, 312);
            close.Size = new Size(178, 52);
            close.FlatStyle = FlatStyle.Flat;
            close.FlatAppearance.BorderColor = Color.FromArgb(218, 217, 224);
            close.BackColor = Color.White;
            close.ForeColor = Color.FromArgb(48, 49, 56);
            close.Cursor = Cursors.Hand;
            close.Font = new Font("Segoe UI", 10F, FontStyle.Bold, GraphicsUnit.Point);
            close.Text = "Đóng phần mềm";
            close.Click += delegate { Close(); };
            Controls.Add(close);

            AcceptButton = update;
            CancelButton = close;
        }
    }

    /// <summary>
    /// Native Windows host for the local EditorVoice web UI.  The Edge WebView2
    /// rendering engine remains a child control; it is not opened as a browser app.
    /// Therefore the taskbar and window icon are owned by EditorVoice.exe.
    /// </summary>
    internal sealed class EditorVoiceForm : Form
    {
        private readonly Label _status;
        private readonly ProgressBar _progress;
        private volatile bool _closing;
        private IntPtr _controller;
        private IntPtr _webView;
        private ICoreWebView2Environment _environment;
        private ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler _environmentHandler;
        private ICoreWebView2CreateCoreWebView2ControllerCompletedHandler _controllerHandler;

        internal EditorVoiceForm()
        {
            Text = string.Empty;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(500, 214);
            MinimumSize = new Size(960, 640);
            BackColor = Color.FromArgb(247, 246, 241);
            Font = new Font("Segoe UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            _status = new Label();
            _status.AutoSize = false;
            _status.ForeColor = Color.FromArgb(92, 94, 104);
            _status.Location = new Point(36, 86);
            _status.Size = new Size(420, 28);
            _status.Text = "Đang khởi động ứng dụng…";
            Controls.Add(_status);

            _progress = new ProgressBar();
            _progress.Location = new Point(36, 132);
            _progress.Size = new Size(428, 17);
            _progress.Style = ProgressBarStyle.Marquee;
            _progress.MarqueeAnimationSpeed = 28;
            Controls.Add(_progress);

            Shown += delegate { ThreadPool.QueueUserWorkItem(delegate { StartServer(); }); };
            Resize += delegate { ResizeWebView(); };
            FormClosing += delegate
            {
                _closing = true;
                CloseWebView();
                Program.StopProcess(Program.ServerProcess);
            };
        }

        private void StartServer()
        {
            try
            {
                Program.Log("Preparing local runtime.");
                string installRoot = AppDomain.CurrentDomain.BaseDirectory;
                string python = Path.Combine(installRoot, "runtime", "pythonw.exe");
                string appRoot = Path.Combine(installRoot, "app");
                string bootstrap = Path.Combine(appRoot, "apps", "desktop_bootstrap.py");
                string sitePackages = Path.Combine(installRoot, "runtime", "Lib", "site-packages");
                string sourceRoot = Path.Combine(appRoot, "src");

                if (!File.Exists(python) || !File.Exists(bootstrap))
                    throw new FileNotFoundException("Bộ ứng dụng chưa đầy đủ. Hãy cài lại EditorVoice.");

                string dataRoot = Program.GetDataRoot();
                Directory.CreateDirectory(dataRoot);
                Directory.CreateDirectory(Path.Combine(dataRoot, "cloned_voices"));
                Directory.CreateDirectory(Path.Combine(dataRoot, "webview-profile"));

                int port = FindAvailablePort();
                // A unique query prevents WebView2 from restoring a stale document
                // from its persistent profile after the application is updated.
                string url = "http://127.0.0.1:" + port + "/?build=1.2.30&release=30082600&nonce=" + Guid.NewGuid().ToString("N");
                UpdateStatus("Đang chuẩn bị máy chủ giọng nói…");

                ProcessStartInfo serverInfo = new ProcessStartInfo();
                serverInfo.FileName = python;
                serverInfo.Arguments = Quote(bootstrap);
                serverInfo.WorkingDirectory = appRoot;
                serverInfo.UseShellExecute = false;
                serverInfo.CreateNoWindow = true;
                serverInfo.EnvironmentVariables["PYTHONPATH"] = appRoot + ";" + sourceRoot + ";" + sitePackages;
                serverInfo.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
                serverInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
                serverInfo.EnvironmentVariables["VIENEU_NO_BROWSER"] = "1";
                serverInfo.EnvironmentVariables["VIENEU_PORT"] = port.ToString();
                serverInfo.EnvironmentVariables["VIENEU_APP_DATA_DIR"] = dataRoot;
                serverInfo.EnvironmentVariables["VIENEU_CLONE_DIR"] = Path.Combine(dataRoot, "cloned_voices");

                Program.ServerProcess = Process.Start(serverInfo);
                Program.Log("Server process started: " + Program.ServerProcess.Id);
                WaitForServer(url, Program.ServerProcess, TimeSpan.FromSeconds(90));
                if (_closing) return;

                UpdateStatus("Đang mở giao diện EditorVoice…");
                SafeInvoke(delegate { CreateEmbeddedWebView(url, Path.Combine(dataRoot, "webview-profile")); });

                while (!_closing && Program.ServerProcess != null && !Program.ServerProcess.HasExited)
                    Thread.Sleep(500);
                if (!_closing)
                    SafeInvoke(delegate { FailAndClose("Máy chủ giọng nói đã dừng. Hãy mở lại EditorVoice."); });
            }
            catch (Exception error)
            {
                Program.Log(error.ToString());
                Program.StopProcess(Program.ServerProcess);
                SafeInvoke(delegate
                {
                    string logPath = Path.Combine(Program.GetDataRoot(), "logs", "launcher.log");
                    FailAndClose(error.Message + "\n\nNhật ký: " + logPath);
                });
            }
        }

        private void CreateEmbeddedWebView(string url, string userDataFolder)
        {
            if (_closing) return;
            try
            {
                _environmentHandler = new EnvironmentCompletedHandler(this, url);
                WebView2Runtime.CreateEnvironment(userDataFolder, _environmentHandler);
            }
            catch (Exception error)
            {
                Program.Log(error.ToString());
                FailAndClose(
                    "Không thể khởi động thành phần hiển thị của EditorVoice. " +
                    "Hãy cài Microsoft Edge WebView2 Runtime rồi mở lại.\n\n" + error.Message
                );
            }
        }

        internal void OnEnvironmentCreated(int errorCode, IntPtr environmentPointer, string url)
        {
            if (_closing)
            {
                if (environmentPointer != IntPtr.Zero) { try { Marshal.Release(environmentPointer); } catch { } }
                return;
            }
            bool releaseEnvironment = environmentPointer != IntPtr.Zero;
            try
            {
                ThrowForHResult(errorCode);
                if (environmentPointer == IntPtr.Zero) throw new InvalidOperationException("Không nhận được môi trường WebView2.");

                _environment = (ICoreWebView2Environment)Marshal.GetObjectForIUnknown(environmentPointer);
                _controllerHandler = new ControllerCompletedHandler(this, url);
                int result = _environment.CreateCoreWebView2Controller(Handle, _controllerHandler);
                ThrowForHResult(result);
            }
            catch (Exception error)
            {
                Program.Log(error.ToString());
                FailAndClose("Không thể tạo cửa sổ EditorVoice.\n\n" + error.Message);
            }
            finally
            {
                if (releaseEnvironment)
                {
                    try { Marshal.Release(environmentPointer); } catch { }
                }
            }
        }

        internal void OnControllerCreated(int errorCode, IntPtr controllerPointer, string url)
        {
            if (_closing)
            {
                if (controllerPointer != IntPtr.Zero) { try { Marshal.Release(controllerPointer); } catch { } }
                return;
            }
            bool releaseController = controllerPointer != IntPtr.Zero;
            try
            {
                ThrowForHResult(errorCode);
                if (controllerPointer == IntPtr.Zero) throw new InvalidOperationException("Không nhận được bộ điều khiển WebView2.");

                _controller = controllerPointer;
                releaseController = false;
                IntPtr webView;
                int result = InvokeCom<ControllerGetCoreWebView2>(_controller, 25)(_controller, out webView);
                ThrowForHResult(result);
                if (webView == IntPtr.Zero) throw new InvalidOperationException("Không nhận được giao diện WebView2.");
                _webView = webView;

                ResizeWebView();
                result = InvokeCom<CoreWebView2Navigate>(_webView, 5)(_webView, url);
                ThrowForHResult(result);

                _status.Visible = false;
                _progress.Visible = false;
                MinimumSize = new Size(960, 640);
                WindowState = FormWindowState.Maximized;
                Program.Log("Embedded WebView2 initialized.");
            }
            catch (Exception error)
            {
                Program.Log(error.ToString());
                FailAndClose("Không thể mở giao diện EditorVoice.\n\n" + error.Message);
            }
            finally
            {
                if (releaseController)
                {
                    try { Marshal.Release(controllerPointer); } catch { }
                }
            }
        }

        private void ResizeWebView()
        {
            if (_controller == IntPtr.Zero || IsDisposed) return;
            try
            {
                NativeRect bounds = new NativeRect();
                bounds.Left = 0;
                bounds.Top = 0;
                bounds.Right = ClientSize.Width;
                bounds.Bottom = ClientSize.Height;
                InvokeCom<ControllerPutBounds>(_controller, 6)(_controller, bounds);
            }
            catch { }
        }

        private void CloseWebView()
        {
            if (_controller != IntPtr.Zero)
            {
                try { InvokeCom<ControllerClose>(_controller, 24)(_controller); } catch { }
            }
            if (_webView != IntPtr.Zero)
            {
                try { Marshal.Release(_webView); } catch { }
                _webView = IntPtr.Zero;
            }
            if (_controller != IntPtr.Zero)
            {
                try { Marshal.Release(_controller); } catch { }
                _controller = IntPtr.Zero;
            }
            if (_environment != null)
            {
                try { Marshal.ReleaseComObject(_environment); } catch { }
                _environment = null;
            }
            _controllerHandler = null;
            _environmentHandler = null;
        }

        private void FailAndClose(string message)
        {
            if (_closing || IsDisposed) return;
            MessageBox.Show(message, "Không thể mở EditorVoice", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }

        private void UpdateStatus(string text)
        {
            SafeInvoke(delegate { _status.Text = text; });
        }

        private void SafeInvoke(MethodInvoker action)
        {
            if (_closing || IsDisposed) return;
            try { BeginInvoke(action); } catch { }
        }

        private static int FindAvailablePort()
        {
            TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            int port = ((IPEndPoint)listener.LocalEndpoint).Port;
            listener.Stop();
            return port;
        }

        private static void WaitForServer(string baseUrl, Process process, TimeSpan timeout)
        {
            DateTime deadline = DateTime.UtcNow.Add(timeout);
            while (DateTime.UtcNow < deadline)
            {
                if (process == null || process.HasExited)
                    throw new InvalidOperationException("Máy chủ giọng nói đã dừng khi đang khởi động.");
                try
                {
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(baseUrl + "api/health");
                    request.Timeout = 700;
                    request.ReadWriteTimeout = 700;
                    request.Proxy = null;
                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    {
                        if ((int)response.StatusCode >= 200 && (int)response.StatusCode < 300) return;
                    }
                }
                catch { }
                Thread.Sleep(250);
            }
            throw new TimeoutException("EditorVoice mất quá nhiều thời gian để khởi động.");
        }

        private static string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private static void ThrowForHResult(int result)
        {
            if (result < 0) Marshal.ThrowExceptionForHR(result);
        }

        private static T InvokeCom<T>(IntPtr instance, int vtableIndex) where T : class
        {
            IntPtr vtable = Marshal.ReadIntPtr(instance);
            IntPtr method = Marshal.ReadIntPtr(vtable, vtableIndex * IntPtr.Size);
            return (T)(object)Marshal.GetDelegateForFunctionPointer(method, typeof(T));
        }
    }

    [ComImport]
    [Guid("B96D755E-0319-4E92-A296-23436F46A1FC")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface ICoreWebView2Environment
    {
        [PreserveSig]
        int CreateCoreWebView2Controller(IntPtr parentWindow, ICoreWebView2CreateCoreWebView2ControllerCompletedHandler handler);
    }

    [Guid("4E8A3389-C9D8-4BD2-B6B5-124FEE6CC14D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [ComVisible(true)]
    public interface ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler
    {
        [PreserveSig]
        int Invoke(int errorCode, IntPtr createdEnvironment);
    }

    [Guid("6C4819F3-C9B7-4260-8127-C9F5BDE7F68C")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [ComVisible(true)]
    public interface ICoreWebView2CreateCoreWebView2ControllerCompletedHandler
    {
        [PreserveSig]
        int Invoke(int errorCode, IntPtr createdController);
    }

    [ComVisible(true)]
    public sealed class EnvironmentCompletedHandler : ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler
    {
        private readonly EditorVoiceForm _form;
        private readonly string _url;

        internal EnvironmentCompletedHandler(EditorVoiceForm form, string url)
        {
            _form = form;
            _url = url;
        }

        public int Invoke(int errorCode, IntPtr createdEnvironment)
        {
            try
            {
                if (createdEnvironment != IntPtr.Zero) Marshal.AddRef(createdEnvironment);
                _form.BeginInvoke(new MethodInvoker(delegate { _form.OnEnvironmentCreated(errorCode, createdEnvironment, _url); }));
            }
            catch { }
            return 0;
        }
    }

    [ComVisible(true)]
    public sealed class ControllerCompletedHandler : ICoreWebView2CreateCoreWebView2ControllerCompletedHandler
    {
        private readonly EditorVoiceForm _form;
        private readonly string _url;

        internal ControllerCompletedHandler(EditorVoiceForm form, string url)
        {
            _form = form;
            _url = url;
        }

        public int Invoke(int errorCode, IntPtr createdController)
        {
            try
            {
                if (createdController != IntPtr.Zero) Marshal.AddRef(createdController);
                _form.BeginInvoke(new MethodInvoker(delegate { _form.OnControllerCreated(errorCode, createdController, _url); }));
            }
            catch { }
            return 0;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeRect
    {
        internal int Left;
        internal int Top;
        internal int Right;
        internal int Bottom;
    }

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    internal delegate int ControllerPutBounds(IntPtr self, NativeRect bounds);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    internal delegate int ControllerGetCoreWebView2(IntPtr self, out IntPtr webView);

    [UnmanagedFunctionPointer(CallingConvention.StdCall, CharSet = CharSet.Unicode)]
    internal delegate int CoreWebView2Navigate(IntPtr self, [MarshalAs(UnmanagedType.LPWStr)] string uri);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    internal delegate int ControllerClose(IntPtr self);

    internal static class WebView2Runtime
    {
        private static IntPtr _module;
        private static CreateWebViewEnvironmentWithOptionsInternalDelegate _createEnvironment;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr LoadLibrary(string fileName);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr module, string procedureName);

        [UnmanagedFunctionPointer(CallingConvention.StdCall, CharSet = CharSet.Unicode)]
        private delegate int CreateWebViewEnvironmentWithOptionsInternalDelegate(
            [MarshalAs(UnmanagedType.Bool)] bool checkRunningInstance,
            int runtimeType,
            [MarshalAs(UnmanagedType.LPWStr)] string userDataFolder,
            IntPtr environmentOptions,
            ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler environmentCreatedHandler
        );

        internal static void CreateEnvironment(string userDataFolder, ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler handler)
        {
            if (_createEnvironment == null)
            {
                string modulePath = FindRuntimeModule();
                if (String.IsNullOrEmpty(modulePath))
                    throw new FileNotFoundException("Không tìm thấy Microsoft Edge WebView2 Runtime trên máy này.");

                _module = LoadLibrary(modulePath);
                if (_module == IntPtr.Zero) throw new InvalidOperationException("Không thể nạp Microsoft Edge WebView2 Runtime.");

                IntPtr function = GetProcAddress(_module, "CreateWebViewEnvironmentWithOptionsInternal");
                if (function == IntPtr.Zero)
                    throw new MissingMethodException("Microsoft Edge WebView2 Runtime không hỗ trợ phiên bản EditorVoice này.");
                _createEnvironment = (CreateWebViewEnvironmentWithOptionsInternalDelegate)
                    Marshal.GetDelegateForFunctionPointer(function, typeof(CreateWebViewEnvironmentWithOptionsInternalDelegate));
            }

            int result = _createEnvironment(true, 0, userDataFolder, IntPtr.Zero, handler);
            if (result < 0) Marshal.ThrowExceptionForHR(result);
        }

        private static string FindRuntimeModule()
        {
            string[] roots = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "EdgeWebView", "Application"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "EdgeWebView", "Application")
            };

            for (int rootIndex = 0; rootIndex < roots.Length; rootIndex++)
            {
                string root = roots[rootIndex];
                if (!Directory.Exists(root)) continue;
                string[] versions = Directory.GetDirectories(root);
                Array.Sort(versions, StringComparer.OrdinalIgnoreCase);
                for (int index = versions.Length - 1; index >= 0; index--)
                {
                    string candidate = Path.Combine(versions[index], "EBWebView", "x64", "EmbeddedBrowserWebView.dll");
                    if (File.Exists(candidate)) return candidate;
                }
            }
            return null;
        }
    }
}
