// 灵枢桌面版 —— 自带窗口的 Windows 客户端（WinForms + WebView2）
//
// 为什么要有它：控制台是本地 Web 服务，之前只能双击 .cmd / .exe 开个黑窗口，
// 再自己去浏览器里开 127.0.0.1:8010。这对「装成软件给人用」来说缺三样东西：
//   1. 没有自己的窗口 —— 浏览器标签页里夹着一堆别的页面，关标签就等于关服务，
//      地址栏还能被误改成别的站点；
//   2. 环境出问题只有命令行报错，用户看不懂也复制不出来；
//   3. 起服务、等就绪、停服务全靠手工。
// 这个程序把这三件事收进一个窗口：左边是环境自检与一键修复，右边是内嵌的
// WebView2（真正嵌在本进程里的浏览器控件，不是外部标签页），关窗口即停服务。
//
// 语言版本：随 Windows 自带的 csc.exe 只支持到 C# 5，所以这里不用字符串插值、
// 不用 ?. / => 成员、不用 nameof，写法保守一点换来「不需要装 .NET SDK 也能编」。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SpiritScoutDesktop
{
    /// <summary>
    /// 把内嵌浏览器需要的三个 DLL 以资源形式塞进 exe，首次运行时解到
    /// %LOCALAPPDATA%\SpiritScout\lib 再从那儿加载——这样发出去就是一个
    /// 独立 exe，不用随包带一堆 DLL，也不会因为 DLL 缺失而白屏。
    /// </summary>
    internal static class Runtime
    {
        private const string ManagedCore = "Microsoft.Web.WebView2.Core.dll";
        private const string ManagedWinForms = "Microsoft.Web.WebView2.WinForms.dll";
        private const string NativeLoader = "WebView2Loader.dll";
        private const string Marker = "1.0.2903.40";   // 与 build-desktop.ps1 里的 SDK 版本一致

        internal static string LibDir { get; private set; }
        internal static string LastError { get; private set; }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetDllDirectory(string path);

        internal static void Prepare()
        {
            try
            {
                string baseDir = ResolveLibDir();
                Directory.CreateDirectory(baseDir);
                Extract("wv2.core", Path.Combine(baseDir, ManagedCore));
                Extract("wv2.winforms", Path.Combine(baseDir, ManagedWinForms));
                Extract("wv2.loader", Path.Combine(baseDir, NativeLoader));
                LibDir = baseDir;

                // 关键：用 Load(byte[]) 而不是 LoadFrom。仓库放在桌面同步目录 / 网络盘时，
                // LoadFrom 会被 CLR 判成「从网络位置加载」并抛 0x80131515，表现就是
                // 内嵌浏览器起不来、只剩一个报错框。
                AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs args)
                {
                    string name = new AssemblyName(args.Name).Name;
                    string path = Path.Combine(baseDir, name + ".dll");
                    if (!File.Exists(path)) { return null; }
                    try { return Assembly.Load(File.ReadAllBytes(path)); }
                    catch (Exception) { return null; }
                };
                SetDllDirectory(baseDir);

                // 预加载一次：窗体类型里有 WebView2 字段，类型加载发生在窗体构造时，
                // 这一步能保证到那时程序集已经在域里了。
                LoadManaged(Path.Combine(baseDir, ManagedCore));
                LoadManaged(Path.Combine(baseDir, ManagedWinForms));
            }
            catch (Exception ex)
            {
                LastError = ex.ToString();
                // 解不出来就没法起内嵌浏览器：把原因写进程序目录，别让人对着白屏猜
                try
                {
                    File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                        "desktop-runtime-error.txt"), LastError, Encoding.UTF8);
                }
                catch (Exception) { }
            }
        }

        /// <summary>
        /// 放解压 DLL 的目录。AppData 在部分机器/策略下不可写（实测会抛
        /// UnauthorizedAccessException），所以留三级：AppData → 程序目录 → 临时目录。
        /// 全都不行就抛出去，让上层退到「用浏览器打开」。
        /// </summary>
        private static string ResolveLibDir()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            List<string> probes = new List<string>();
            if (!string.IsNullOrEmpty(localAppData))
            {
                probes.Add(Path.Combine(localAppData, "SpiritScout", "lib", Marker));
            }
            probes.Add(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "灵枢桌面版-lib", Marker));
            probes.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-lib", Marker));

            List<string> errors = new List<string>();
            foreach (string candidate in probes)
            {
                try
                {
                    Directory.CreateDirectory(candidate);
                    string probe = Path.Combine(candidate, ".writable");
                    File.WriteAllText(probe, "ok", Encoding.UTF8);
                    File.Delete(probe);
                    return candidate;
                }
                catch (Exception ex)
                {
                    errors.Add(candidate + " → " + ex.GetType().Name + ": " + ex.Message);
                }
            }
            throw new IOException("三处候选目录都写不进去：" + string.Join(" | ", errors.ToArray()));
        }
        private static readonly List<Assembly> Loaded = new List<Assembly>();

        private static void LoadManaged(string path)
        {
            try
            {
                Loaded.Add(Assembly.Load(File.ReadAllBytes(path)));
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine("预加载失败 " + path + ": " + ex.Message);
            }
        }
        private static void Extract(string resourceName, string target)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream source = asm.GetManifestResourceStream(resourceName))
            {
                if (source == null) { throw new InvalidOperationException("缺资源：" + resourceName); }
                // 大小与长度都一致就跳过，避免每次启动都重写文件
                FileInfo info = new FileInfo(target);
                if (info.Exists && info.Length == source.Length) { return; }
                using (FileStream output = File.Create(target))
                {
                    source.CopyTo(output);
                }
            }
        }
    }

    /// <summary>
    /// 单文件版：exe 末尾挂着一个 zip（里面是 py\ 与 configs\），尾部 24 字节是
    /// [载荷长度][保留][标记]。首次启动把载荷倒出来解到可写目录，之后直接用。
    /// 这样发出去就是「一个 exe，双击能跑」，不用带一堆文件、也不用机器上装 Python。
    /// </summary>
    internal static class BundledRuntime
    {
        private const string Marker = "SSRTPAY1";    // 尾部最后 8 字节；改了就互不认
        // 解出来的树得能自证完整：清单是 大小<TAB>相对路径，按行读，不引 JSON 库
        private const string ManifestName = "runtime.manifest.tsv";
        private const string ReadyMarker = ".ready";
        internal const string UserDataFolder = ".spiritscout";
        private const int TrailerSize = 40;          // 8 长度 + 24 校验 + 8 标记
        private const int HashBytes = 24;            // 载荷 SHA-256 只存前 24 字节，够防下载残缺

        internal static string Root { get; private set; }
        internal static string Error { get; private set; }

        /// <summary>当前这个 exe 是不是带载荷的单文件版。</summary>
        internal static bool HasPayload()
        {
            long offset;
            long length;
            try { return ReadTrailer(Application.ExecutablePath, out offset, out length); }
            catch (Exception) { return false; }
        }

        private static bool ReadTrailer(string self, out long offset, out long length)
        {
            offset = 0;
            length = 0;
            using (FileStream fs = File.OpenRead(self))
            {
                if (fs.Length < TrailerSize + 1024) { return false; }
                fs.Seek(-TrailerSize, SeekOrigin.End);
                byte[] tail = new byte[TrailerSize];
                if (fs.Read(tail, 0, TrailerSize) != TrailerSize) { return false; }
                string marker = Encoding.ASCII.GetString(tail, 32, 8);
                if (marker != Marker) { return false; }
                length = BitConverter.ToInt64(tail, 0);
                offset = fs.Length - TrailerSize - length;
                return length > 0 && offset > 0;
            }
        }

        /// <summary>尾标里记的载荷 SHA-256 前 24 字节；读不到就返回空。</summary>
        private static byte[] ReadExpectedHash(string self)
        {
            using (FileStream fs = File.OpenRead(self))
            {
                if (fs.Length < TrailerSize) { return new byte[0]; }
                fs.Seek(-TrailerSize, SeekOrigin.End);
                byte[] tail = new byte[TrailerSize];
                if (fs.Read(tail, 0, TrailerSize) != TrailerSize) { return new byte[0]; }
                byte[] hash = new byte[HashBytes];
                Array.Copy(tail, 8, hash, 0, HashBytes);
                return hash;
            }
        }

        /// <summary>倒出来的载荷够不够完整？下载断了/被截断的 exe 会在这里露馅。</summary>
        private static bool VerifyPayload(string zip, byte[] expected)
        {
            if (expected == null || expected.Length != HashBytes) { return true; }
            using (FileStream fs = File.OpenRead(zip))
            using (SHA256 sha = SHA256.Create())
            {
                byte[] actual = sha.ComputeHash(fs);
                for (int i = 0; i < HashBytes; i++)
                {
                    if (actual[i] != expected[i]) { return false; }
                }
            }
            return true;
        }

        /// <summary>
        /// 运行时能不能用。光看 .ready 不够：本机实测过杀毒/EDR 把安装目录里某些
        /// 文件单独清理掉，.ready 还在、python 还在，但缺一个知识库模块就让首页 500，
        /// 所以这里额外抽查几个关键文件。
        /// <para>requireMarker=false 用在**刚解压完、标记还没写**的那一刻——
        /// 否则会因为「没有 .ready」判定失败，白解三次。</para>
        /// </summary>
        private static bool Ready(string dir, bool requireMarker)
        {
            if (!File.Exists(Path.Combine(dir, "py", "python.exe"))) { return false; }
            if (!File.Exists(Path.Combine(dir, "configs", "system.yaml"))) { return false; }
            if (requireMarker && !File.Exists(Path.Combine(dir, ReadyMarker))) { return false; }
            string site = Path.Combine(dir, "py", "Lib", "site-packages");
            string[] sentinels = new string[]
            {
                Path.Combine(site, "spiritscout", "web", "app.py"),
                Path.Combine(site, "spiritscout", "knowledge", "seed.py"),
                Path.Combine(site, "spiritscout", "knowledge", "data", "seed.json"),
                Path.Combine(site, "litellm", "__init__.py"),
            };
            foreach (string path in sentinels)
            {
                if (!File.Exists(path)) { return false; }
            }
            return true;
        }

        /// <summary>按清单核对解出来的树：缺文件或大小不符都算坏。返回问题描述（最多几条）。</summary>
        private static string VerifyTree(string dir, out int broken)
        {
            broken = 0;
            string manifest = Path.Combine(dir, ManifestName);
            if (!File.Exists(manifest)) { return ""; }   // 老载荷没有清单，别误判成坏
            string[] lines;
            try { lines = File.ReadAllLines(manifest); }
            catch (IOException) { return ""; }
            List<string> problems = new List<string>();
            foreach (string raw in lines)
            {
                string line = raw.Trim();
                if (line.Length == 0 || line[0] == '#') { continue; }
                int tab = line.IndexOf('\t');
                if (tab <= 0) { continue; }
                long size;
                if (!long.TryParse(line.Substring(0, tab), out size)) { continue; }
                string rel = line.Substring(tab + 1).Replace('/', Path.DirectorySeparatorChar);
                string full = Path.Combine(dir, rel);
                FileInfo info = new FileInfo(full);
                if (!info.Exists || info.Length != size)
                {
                    broken++;
                    if (problems.Count < 5) { problems.Add(rel.Replace(Path.DirectorySeparatorChar, '/')); }
                }
            }
            if (broken == 0) { return ""; }
            return string.Join("、", problems.ToArray()) + (broken > problems.Count ? " 等 " + broken + " 个" : "");
        }

        /// <summary>解出运行时并返回程序目录；失败返回 null，原因写进 Error。</summary>
        internal static string Ensure(Action<string> progress)
        {
            Error = null;
            string self = Application.ExecutablePath;
            long offset;
            long length;
            if (!ReadTrailer(self, out offset, out length))
            {
                Error = "exe 尾部没有运行时载荷";
                return null;
            }
            string tag = length.ToString() + "-" + Fingerprint(self, offset).ToString("x8");

            List<string> probes = new List<string>();
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                probes.Add(Path.Combine(localAppData, "SpiritScout", "runtime", tag));
            }
            string exeDir = Path.GetDirectoryName(self);
            if (!string.IsNullOrEmpty(exeDir))
            {
                probes.Add(Path.Combine(exeDir, "灵枢运行时-" + tag));
            }
            probes.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-runtime", tag));

            // 已经解过一次就别再动：同一台机器第二次启动直接进界面。
            // 但 .ready 在、关键文件却缺（杀软清理过）时要认账，清掉重解。
            foreach (string candidate in probes)
            {
                if (Ready(candidate, true)) { Root = candidate; return candidate; }
                if (File.Exists(Path.Combine(candidate, ReadyMarker)))
                {
                    progress("上次解出来的运行时缺文件，重解一遍：" + candidate);
                    try { Directory.Delete(candidate, true); } catch (Exception) { }
                }
            }

            List<string> errors = new List<string>();
            foreach (string candidate in probes)
            {
                try
                {
                    Directory.CreateDirectory(candidate);
                    progress("解出运行时到：" + candidate);
                    string zip = Path.Combine(candidate, "runtime.zip");
                    ExtractPayload(self, offset, length, zip, progress);
                    if (!VerifyPayload(zip, ReadExpectedHash(self)))
                    {
                        throw new InvalidOperationException("载荷校验不通过（下载不完整或被改过）");
                    }
                    progress("展开 " + (length / 1048576) + " MB，两万多个文件，耐心等一下…");
                    Expand(zip, candidate);
                    try { File.Delete(zip); } catch (IOException) { }
                    if (!File.Exists(Path.Combine(candidate, "py", "python.exe")))
                    {
                        throw new InvalidOperationException("解开后没有 py\\python.exe");
                    }
                    int broken;
                    string problems = VerifyTree(candidate, out broken);
                    if (broken > 0)
                    {
                        throw new InvalidOperationException(
                            "解开后缺 " + broken + " 个文件（可能被杀毒软件清理）：" + problems);
                    }
                    if (!Ready(candidate, false))
                    {
                        throw new InvalidOperationException("解出来的运行时没通过自检");
                    }
                    AdoptUserData(candidate, progress);
                    File.WriteAllText(Path.Combine(candidate, ReadyMarker), tag, Encoding.UTF8);
                    Root = candidate;
                    return candidate;
                }
                catch (Exception ex)
                {
                    errors.Add(candidate + " → " + ex.Message);
                    try { Directory.Delete(candidate, true); } catch (Exception) { }
                }
            }
            Error = string.Join("；", errors.ToArray());
            return null;
        }

        /// <summary>
        /// 换了新版本的单文件 exe，运行时会解到新目录（目录名带载荷指纹），而模型密钥、
        /// 会话、知识库都在上一份运行时的 .spiritscout 里。不搬的话，用户升个版本就发现
        /// 「密钥没了、历史也没了」，看起来就像环境配置出错。这里把同目录下最新的那份
        /// .spiritscout 复制过来（新目录里还没有数据时才做）。
        /// </summary>
        internal static void AdoptUserData(string target, Action<string> progress)
        {
            string mine = Path.Combine(target, UserDataFolder);
            if (Directory.Exists(mine) && Directory.GetFileSystemEntries(mine).Length > 0) { return; }
            string parent = Path.GetDirectoryName(target.TrimEnd(Path.DirectorySeparatorChar));
            if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent)) { return; }

            string best = null;
            DateTime newest = DateTime.MinValue;
            foreach (string sibling in Directory.GetDirectories(parent))
            {
                if (string.Equals(Path.GetFullPath(sibling).TrimEnd(Path.DirectorySeparatorChar),
                                  Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar),
                                  StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                string data = Path.Combine(sibling, UserDataFolder);
                if (!Directory.Exists(data) || Directory.GetFileSystemEntries(data).Length == 0) { continue; }
                DateTime stamp = Directory.GetLastWriteTimeUtc(data);
                if (stamp > newest) { newest = stamp; best = data; }
            }
            if (best == null) { return; }

            try
            {
                CopyTree(best, mine);
                if (progress != null) { progress("[+] 已把上一次的配置与数据带过来：" + best); }
            }
            catch (IOException ex)
            {
                if (progress != null) { progress("[!] 旧数据没搬全（可以手动拷 " + best + "）：" + ex.Message); }
            }
            catch (UnauthorizedAccessException ex)
            {
                if (progress != null) { progress("[!] 旧数据没搬全（权限不够）：" + ex.Message); }
            }
        }

        private static void CopyTree(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (string file in Directory.GetFiles(from))
            {
                File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            }
            foreach (string dir in Directory.GetDirectories(from))
            {
                CopyTree(dir, Path.Combine(to, Path.GetFileName(dir)));
            }
        }

        /// <summary>载荷前 64 KB 的 FNV-1a：同一份运行时算出来的值一致，攒成缓存目录名。</summary>
        private static uint Fingerprint(string self, long offset)
        {
            uint hash = 2166136261;
            using (FileStream fs = File.OpenRead(self))
            {
                fs.Seek(offset, SeekOrigin.Begin);
                byte[] buffer = new byte[65536];
                int read = fs.Read(buffer, 0, buffer.Length);
                for (int i = 0; i < read; i++)
                {
                    hash = (hash ^ buffer[i]) * 16777619;
                }
            }
            return hash;
        }

        private static void ExtractPayload(string self, long offset, long length, string target, Action<string> progress)
        {
            using (FileStream input = File.OpenRead(self))
            using (FileStream output = File.Create(target))
            {
                input.Seek(offset, SeekOrigin.Begin);
                byte[] buffer = new byte[1 << 20];
                long left = length;
                long done = 0;
                while (left > 0)
                {
                    int want = (int)Math.Min(buffer.Length, left);
                    int read = input.Read(buffer, 0, want);
                    if (read <= 0) { throw new IOException("载荷读取提前结束"); }
                    output.Write(buffer, 0, read);
                    left -= read;
                    done += read;
                    if (progress != null && done % (64L << 20) < buffer.Length)
                    {
                        progress("已倒出 " + (done / 1048576) + " / " + (length / 1048576) + " MB");
                    }
                }
            }
        }

        /// <summary>解 zip：优先系统自带的 tar.exe（快），没有就退到 PowerShell 的 Expand-Archive。</summary>
        private static void Expand(string zip, string dir)
        {
            string tar = Path.Combine(Environment.SystemDirectory, "tar.exe");
            if (File.Exists(tar))
            {
                ProcessStartInfo psi = new ProcessStartInfo(tar, "-xf \"" + zip + "\" -C \"" + dir + "\"");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                using (Process p = Process.Start(psi))
                {
                    p.WaitForExit();
                    if (p.ExitCode == 0) { return; }
                }
            }
            ProcessStartInfo ps = new ProcessStartInfo("powershell.exe",
                "-NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '" + zip
                + "' -DestinationPath '" + dir + "' -Force\"");
            ps.UseShellExecute = false;
            ps.CreateNoWindow = true;
            using (Process p = Process.Start(ps))
            {
                p.WaitForExit();
                if (p.ExitCode != 0) { throw new InvalidOperationException("解题失败（tar 与 Expand-Archive 都没成）"); }
            }
        }
    }

    internal static class Program
    {
        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string windowName);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr handle, int command);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr handle);

        [STAThread]
        private static void Main(string[] args)
        {
            bool smoke = args != null && Array.IndexOf(args, "--smoke") >= 0;
            // 这是个 winexe：崩了既没控制台也没弹窗，用户只看到「双击没反应」。
            // 所以先把兜底挂上，崩了至少留下能看的日志和一句人话。
            AppDomain.CurrentDomain.UnhandledException += OnFatal;
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += OnThreadException;
            try
            {
                Runtime.Prepare();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                // WebView2 的用户数据目录是独占的：同时开两个实例，第二个必然起不来。
                // 所以第二次双击只把已有的窗口叫到前面，不再开新的。
                bool created;
                // 冒烟测试要能在「用户正开着灵枢」的时候跑（构建时很常见），
                // 所以它不参与单实例互斥，也别去激活别人已经开着的窗口。
                using (Mutex single = new Mutex(true, "SpiritScoutDesktop-single-instance", out created))
                {
                    if (!created && !smoke)
                    {
                        IntPtr existing = FindWindow(null, "灵枢 · SpiritScout");
                        if (existing != IntPtr.Zero)
                        {
                            ShowWindow(existing, 9);      // SW_RESTORE
                            SetForegroundWindow(existing);
                        }
                        return;
                    }
                    if (smoke) { Application.Run(new DesktopForm(true)); GC.KeepAlive(single); return; }
                    Application.Run(new DesktopForm(false));
                    GC.KeepAlive(single);
                }
            }
            catch (Exception ex)
            {
                Report(ex);
            }
        }

        private static void OnFatal(object sender, UnhandledExceptionEventArgs e)
        {
            Report(e.ExceptionObject as Exception ?? new Exception("未知致命错误"));
        }

        private static void OnThreadException(object sender, ThreadExceptionEventArgs e)
        {
            Report(e.Exception);
        }

        private static void Report(Exception ex)
        {
            string path = "（日志没写成：三处候选目录都不可写）";
            string fileName = "crash-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log";
            List<string> dirs = new List<string>();
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData)) { dirs.Add(Path.Combine(localAppData, "SpiritScout", "logs")); }
            dirs.Add(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs"));
            dirs.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-logs"));
            foreach (string dir in dirs)
            {
                try
                {
                    Directory.CreateDirectory(dir);
                    string candidate = Path.Combine(dir, fileName);
                    File.WriteAllText(candidate, ex.ToString(), Encoding.UTF8);
                    path = candidate;
                    break;
                }
                catch (Exception) { }
            }
            try
            {
                MessageBox.Show("灵枢桌面版出错了：\n\n" + ex.Message + "\n\n细节写在这里：\n" + path,
                    "灵枢桌面版", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch (Exception) { }
        }
    }

    internal sealed class DesktopForm : Form
    {
        // 控制台默认端口；被占用时自动换一个，不让人去改配置
        private const int PreferredPort = 8010;
        private const string LogFolderName = "logs";

        // 不是 readonly：单文件版要先开窗、再解运行时，解完才知道真正的程序目录
        private string _repoRoot;      // 仓库根（start-local.ps1 所在目录）；便携/单文件版是程序目录
        private string _packageDir;    // SpiritScout/（pyproject.toml 与 .venv 在这）；便携/单文件版是程序目录
        private string _logDir;
        private string _pythonOverride; // desktop.json 里指定的解释器（便携/单文件版内嵌的那个）
        private bool _portable;         // 便携版：依赖已装进内嵌 Python，没有 venv 也没有 bootstrap.py
        private bool _singleFile;       // 单文件版：exe 尾巴上挂着运行时 zip，首次启动解出来
        private bool _runtimeBroken;    // 单文件版这次没解开运行时（杀软拦、磁盘满、目录不可写）

        private WebView2 _web;          // 延迟创建：内嵌浏览器初始化失败也要能开窗
        private Panel _canvas;          // 主区域：装浏览器控件，兜底时换成一页提示
        private bool _fallbackShown;    // 兜底卡片已经画过，别重复叠
        private Process _server;
        private int _port = PreferredPort;
        private bool _webReady;
        private bool _closing;
        private bool _starting;         // 正在启动：防止重试按钮被连点
        private bool _uiPage;           // 当前显示的是启动页/错误页，别被控制台覆盖
        private string _statusText = "";  // 启动页上那行状态，页面刷新后要补回去
        private static string _shellCss;  // 壳页面共用样式（控制台 base.css+polish.css），读一次缓存
        private readonly object _logLock = new object();
        private StringBuilder _serverErr = new StringBuilder();

        private readonly bool _smokeOnly;

        public DesktopForm(bool smokeOnly)
        {
            _smokeOnly = smokeOnly;
            // 三种形态，优先级从高到低：
            //   1. 单文件版：exe 尾部挂着运行时 zip（build-single.ps1 拼的），先开窗再解；
            //   2. 便携版：exe 旁边的 desktop.json 指路（root=程序目录、python=内嵌解释器）；
            //   3. 仓库版：在仓库根里找 SpiritScout/。
            _singleFile = BundledRuntime.HasPayload();
            DesktopConfig cfg = ReadDesktopConfig();
            if (_singleFile)
            {
                // 真正的程序目录要等运行时解完才知道：先拿 exe 所在目录顶着，日志也先写这儿
                _repoRoot = Path.GetDirectoryName(Application.ExecutablePath);
                _packageDir = _repoRoot;
                _pythonOverride = null;
                _portable = true;
            }
            else if (cfg != null && !string.IsNullOrEmpty(cfg.Root) && Directory.Exists(cfg.Root))
            {
                _repoRoot = cfg.Root;
                // 便携版把 configs/ 放在程序目录；万一有人把整仓塞进来，就认 SpiritScout/ 那层。
                string inner = Path.Combine(cfg.Root, "SpiritScout");
                bool innerHasConfig = File.Exists(Path.Combine(inner, "configs", "system.yaml"));
                _packageDir = innerHasConfig ? inner : cfg.Root;
                _pythonOverride = cfg.Python;
                _portable = true;
                if (cfg.Port > 0) { _port = cfg.Port; }
            }
            else
            {
                _repoRoot = ResolveRepoRoot();
                _packageDir = Path.Combine(_repoRoot, "SpiritScout");
                _pythonOverride = null;
                _portable = false;
            }
            _logDir = Path.Combine(_repoRoot, LogFolderName);

            ApplyAppIcon();
            Text = "灵枢 · SpiritScout";
            StartPosition = FormStartPosition.CenterScreen;
            // 默认 1360×880，但小屏（1366×768 的笔记本）放不下，按工作区收一下；
            // 最小尺寸也跟着屏幕走，否则窗口会顶到屏幕外面去。
            Rectangle work = Screen.FromPoint(Control.MousePosition).WorkingArea;
            int wantW = Math.Min(1360, work.Width - 48);
            int wantH = Math.Min(880, work.Height - 56);
            int minW = Math.Min(1024, Math.Max(760, work.Width - 48));
            int minH = Math.Min(680, Math.Max(560, work.Height - 56));
            MinimumSize = new Size(minW, minH);
            Size = new Size(Math.Max(minW, wantW), Math.Max(minH, wantH));
            // 浅色，和启动页、控制台一个底色；深色会先闪一块黑
            BackColor = Color.FromArgb(246, 247, 249);
            Font = new Font("Microsoft YaHei UI", 9F);

            BuildLayout();
            KeyPreview = true;
            KeyDown += OnShortcut;   // 焦点在窗口自己身上时走这条
            Load += OnLoaded;
            FormClosing += OnClosing;
        }

        private static string ResolveRepoRoot()
        {
            // exe 可能放在仓库根（和 start-local.ps1 同级），也可能被单独拷出去。
            // 先看 exe 所在目录，再看上一级，最后退回当前工作目录。
            string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
            string[] candidates = new string[]
            {
                exeDir,
                Path.GetDirectoryName(exeDir),
                Directory.GetCurrentDirectory(),
            };
            foreach (string dir in candidates)
            {
                if (string.IsNullOrEmpty(dir)) { continue; }
                if (Directory.Exists(Path.Combine(dir, "SpiritScout"))
                    && File.Exists(Path.Combine(dir, "SpiritScout", "pyproject.toml")))
                {
                    return dir;
                }
            }
            return exeDir;
        }

        /// <summary>desktop.json 的内容（便携版用）。字段缺省即视为没配。</summary>
        private sealed class DesktopConfig
        {
            public string Root;
            public string Python;
            public int Port;
        }

        /// <summary>读 exe 旁边的 desktop.json；没有或不合法就返回 null（退回仓库模式）。</summary>
        private static DesktopConfig ReadDesktopConfig()
        {
            string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
            if (string.IsNullOrEmpty(exeDir)) { return null; }
            string path = Path.Combine(exeDir, "desktop.json");
            if (!File.Exists(path)) { return null; }
            string json;
            try { json = File.ReadAllText(path, Encoding.UTF8); }
            catch (Exception) { return null; }

            DesktopConfig cfg = new DesktopConfig();
            string root = JsonField(json, "root");
            if (!string.IsNullOrEmpty(root))
            {
                cfg.Root = Path.IsPathRooted(root) ? root : Path.GetFullPath(Path.Combine(exeDir, root));
            }
            string python = JsonField(json, "python");
            if (!string.IsNullOrEmpty(python))
            {
                cfg.Python = Path.IsPathRooted(python) ? python : Path.GetFullPath(Path.Combine(exeDir, python));
            }
            string port = JsonField(json, "port");
            int parsed;
            if (!string.IsNullOrEmpty(port) && int.TryParse(port, out parsed) && parsed > 0 && parsed < 65536)
            {
                cfg.Port = parsed;
            }
            return cfg;
        }

        /// <summary>够用就好的 JSON 取值：只认一层扁平字符串/数字，不引第三方库。</summary>
        private static string JsonField(string json, string key)
        {
            string quoted = "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"([^\"]*)\"";
            Match m = Regex.Match(json, quoted);
            if (m.Success) { return m.Groups[1].Value; }
            m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?\\d+)");
            return m.Success ? m.Groups[1].Value : null;
        }

        // ---------------- 界面 ----------------

        /// <summary>
        /// 窗口和任务栏的图标。WinForms 不会自动用 exe 里那份——不设 Icon 的话标题栏
        /// 和任务栏一直是 .NET 那个通用图标，看着就像「图标根本没改」。
        /// 优先读构建时嵌进来的 app.icon（和网页 favicon 同一张图），
        /// 拿不到再从 exe 资源里抽。
        /// </summary>
        private void ApplyAppIcon()
        {
            try
            {
                System.IO.Stream stream =
                    typeof(DesktopForm).Assembly.GetManifestResourceStream("app.icon");
                if (stream != null)
                {
                    using (stream)
                    {
                        Icon = new Icon(stream);
                        return;
                    }
                }
            }
            catch (Exception) { }
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { }
        }
        private void BuildLayout()
        {
            // 窗口里只有一样东西：铺满整个窗口的内嵌浏览器。
            // 没有工具栏、没有状态条、没有日志面板——打开就是控制台，
            // 起不来才把这一页换成「环境没准备好」，那页上带重试。
            Padding = new Padding(0);
            Panel canvas = new Panel();
            canvas.Dock = DockStyle.Fill;
            canvas.Padding = new Padding(0);
            canvas.BackColor = BackColor;
            canvas.Controls.Add(CreateWebView());
            Controls.Add(canvas);
            _canvas = canvas;
        }

        /// <summary>
        /// 单独一个方法建 WebView2：引用 WebView2 类型的代码集中在这里，
        /// 于是「DLL 加载不出来」变成这里抛异常、外面 catch 得到，
        /// 而不是整个 BuildLayout 没能 JIT、窗口都开不起来。
        /// </summary>
        private Control CreateWebView()
        {
            try
            {
                _web = new WebView2();
                _web.Dock = DockStyle.Fill;
                try
                {
                    // 控件默认底色是黑的：首帧会闪一块黑板，看着像程序坏了
                    _web.DefaultBackgroundColor = Color.FromArgb(246, 247, 249);
                }
                catch (Exception) { }
                return _web;
            }
            catch (Exception ex)
            {
                _web = null;
                AppendLog("[!] 内嵌浏览器控件建不起来：" + ex.Message);
                return new Panel();
            }
        }

        /// <summary>
        /// 窗口里铺的是 WebView2，焦点几乎总在网页里，窗体的 KeyDown 收不到键。
        /// 所以往每个页面注入一小段脚本，把同样的快捷键转成消息发回来。
        /// </summary>
        private void InstallShortcutBridge()
        {
            const string script =
                "(function(){if(window.__ssKeys)return;window.__ssKeys=1;"
                + "var send=function(a){try{window.chrome.webview.postMessage({action:a});}catch(e){}};"
                + "document.addEventListener('keydown',function(e){"
                + "var k=(e.key||'').toLowerCase();"
                + "if(k==='f5'&&!e.ctrlKey&&!e.altKey){e.preventDefault();send('reload');return;}"
                + "if(!e.ctrlKey||!e.altKey)return;"
                + "if(k==='p'){e.preventDefault();send('pw');}"
                + "else if(k==='l'){e.preventDefault();send('log');}"
                + "else if(k==='o'){e.preventDefault();send('browser');}"
                + "},true);})();";
            try
            {
                if (_webReady && _web.CoreWebView2 != null)
                {
                    Task ignore = _web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(script);
                }
            }
            catch (Exception ex) { AppendLog("[!] 快捷键桥没装上：" + ex.Message); }
        }

        /// <summary>不摆按钮了，功能留成快捷键：F5 刷新、Ctrl+Alt+O 用浏览器开、L 日志、P 密码。</summary>
        private void OnShortcut(object sender, KeyEventArgs e)
        {
            if (e.KeyCode == Keys.F5) { ReloadPage(); e.Handled = true; return; }
            if (!e.Control || !e.Alt) { return; }
            if (e.KeyCode == Keys.O) { OpenExternal(); e.Handled = true; }
            else if (e.KeyCode == Keys.L) { OpenLogFolder(); e.Handled = true; }
            else if (e.KeyCode == Keys.P) { SetPassword(); e.Handled = true; }
        }

        private async void OnLoaded(object sender, EventArgs e)
        {
            if (_smokeOnly)
            {
                // 构建脚本用这个开关：只要窗口能起来就够了，不要真起服务
                await InitWebViewAsync();
                ShowSplash("构建冒烟：窗口正常");
                System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
                timer.Interval = 1200;
                timer.Tick += delegate
                {
                    timer.Stop();
                    // 给构建脚本一个确定的信号：冒烟窗口确实建起来了
                    string mark = Environment.GetEnvironmentVariable("SPIRITSCOUT_SMOKE_MARK");
                    if (!string.IsNullOrEmpty(mark))
                    {
                        try { File.WriteAllText(mark, "ok"); }
                        catch (Exception) { }
                    }
                    Close();
                };
                timer.Start();
                return;
            }
            await StartAppAsync();
        }

        /// <summary>
        /// 打开就自己跑：亮启动页 → 解运行时 → 确认环境 → 起服务 → 换成控制台。
        /// 中途真失败才把窗口换成「环境没准备好」，那页上有重试按钮。
        /// </summary>
        private async Task StartAppAsync()
        {
            if (_starting) { return; }
            _starting = true;
            try
            {
                AppendLog("灵枢桌面版启动。程序目录：" + _repoRoot
                    + (_singleFile ? "（单文件版：运行时随 exe 一起）" : ""));
                _uiPage = true;
                await InitWebViewAsync();
                ShowSplash("正在准备运行时…");
                if (_singleFile) { await UnpackBundledRuntimeAsync(); }
                if (_runtimeBroken) { return; }
                ShowSplash("正在确认运行环境…");
                string python = await EnsureReadyAsync();
                if (python == null)
                {
                    ShowErrorPage(_failTitle, _failLead, _failDetail);
                    return;
                }
                ShowSplash("正在启动控制台…");
                bool ok = await StartServerAsync(python);
                if (!ok) { ShowErrorPage(_failTitle, _failLead, _failDetail); }
            }
            catch (Exception ex)
            {
                AppendLog("[x] 启动失败：" + ex);
                _failTitle = "启动失败";
                _failLead = "灵枢在启动过程中出错中断了。日志里有完整的调用栈。";
                _failDetail = ex.ToString();
                ShowErrorPage(_failTitle, _failLead, _failDetail);
            }
            finally
            {
                _starting = false;
            }
        }

        // ---------------- 启动页 / 错误页 ----------------

        /// <summary>把内嵌页面换成启动页（浅色、带进度条）。重复调用只更新那行字。</summary>
        private void ShowSplash(string text)
        {
            _statusText = text;
            if (_web == null || !_webReady) { return; }
            if (_uiPage && _splashLoaded)
            {
                PushSplashStatus(text);
                return;
            }
            string html = ReadUiHtml("splash.html");
            if (html == null) { return; }
            _uiPage = true;
            _splashLoaded = false;
            _uiHtmlShown = true;
            _web.NavigateToString(html.Replace("{{STATUS}}", EscapeHtml(text)));
            AppendLog("[i] " + text);
        }

        private bool _splashLoaded;    // 启动页已经画出来了
        private bool _uiHtmlShown;     // 这一发 NavigateToString 是我们自己送的页面

        private void PushSplashStatus(string text)
        {
            try
            {
                _web.CoreWebView2.ExecuteScriptAsync("window.ssSet && window.ssSet(" + JsString(text) + ");");
            }
            catch (Exception) { }
        }

        /// <summary>环境不对才走这里：一页说清原因，带重试/日志/浏览器/退出。</summary>
        private void ShowErrorPage(string title, string lead, string detail)
        {
            _uiPage = true;
            _statusText = title;
            AppendLog("[x] " + title + "：" + (detail == null ? "" : detail));
            string html = ReadUiHtml("error.html");
            if (html == null || _web == null || !_webReady)
            {
                MessageBox.Show(title + Environment.NewLine + Environment.NewLine + lead
                    + Environment.NewLine + Environment.NewLine + (detail == null ? "" : detail),
                    "灵枢 · 环境没准备好", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            _uiHtmlShown = true;
            html = html.Replace("{{TITLE}}", EscapeHtml(title))
                       .Replace("{{LEAD}}", EscapeHtml(lead))
                       .Replace("{{DETAIL}}", EscapeHtml(detail == null ? "" : detail));
            _web.NavigateToString(html);
        }

        private string ReadUiHtml(string name)
        {
            try
            {
                Stream stream = typeof(DesktopForm).Assembly.GetManifestResourceStream(name);
                if (stream == null)
                {
                    AppendLog("[!] 找不到内嵌页面 " + name + "（构建时要用 /resource 嵌进去）");
                    return null;
                }
                using (stream)
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                {
                    string html = reader.ReadToEnd();
                    // 壳页面的样式是构建时拼好的（控制台的 base.css + polish.css + 壳自己的排版），
                    // 塞进占位符，页面里就不用再抄一套颜色和控件样式。
                    if (html.IndexOf("{{SHELL_CSS}}", StringComparison.Ordinal) >= 0)
                    {
                        html = html.Replace("{{SHELL_CSS}}", ReadShellCss());
                    }
                    return html;
                }
            }
            catch (Exception ex)
            {
                AppendLog("[!] 读内嵌页面失败：" + ex.Message);
                return null;
            }
        }

        // 窗口壳（启动页 / 错误页 / 设密码）用的那一份样式：构建时由 launcher/ui/shell.css 嵌进 exe，
        // 内容就是控制台的 base.css + polish.css 加上壳自己的排版——壳和控制台永远是同一套样式。
        private string ReadShellCss()
        {
            if (_shellCss != null) { return _shellCss; }
            try
            {
                Stream stream = typeof(DesktopForm).Assembly.GetManifestResourceStream("app.shellcss");
                if (stream != null)
                {
                    using (stream)
                    using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                    {
                        _shellCss = reader.ReadToEnd();
                        return _shellCss;
                    }
                }
                // exe 里没嵌（比如直接从源码树里跑的旧壳）就退回磁盘上的构建产物
                string path = Path.Combine(_packageDir, "launcher", "ui", "shell.css");
                if (File.Exists(path))
                {
                    _shellCss = File.ReadAllText(path, Encoding.UTF8);
                    return _shellCss;
                }
                AppendLog("[!] 找不到窗口壳样式 shell.css（构建时要用 /resource:app.shellcss 嵌进去）");
            }
            catch (Exception ex)
            {
                AppendLog("[!] 读窗口壳样式失败：" + ex.Message);
            }
            _shellCss = "";
            return _shellCss;
        }

        private static string EscapeHtml(string text)
        {
            if (text == null) { return ""; }
            return text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");
        }

        private static string JsString(string text)
        {
            if (text == null) { return "\"\""; }
            StringBuilder builder = new StringBuilder("\"");
            foreach (char ch in text)
            {
                if (ch == '\\') { builder.Append("\\\\"); }
                else if (ch == '"') { builder.Append("\\\""); }
                else if (ch == '\r') { builder.Append("\\r"); }
                else if (ch == '\n') { builder.Append("\\n"); }
                else if (ch == '<') { builder.Append("\\u003c"); }
                else { builder.Append(ch); }
            }
            builder.Append("\"");
            return builder.ToString();
        }

        /// <summary>错误页上的按钮点下来走这里；也挡住来源不明的消息。</summary>
        private void HandleUiAction(string payload)
        {
            if (payload == null) { return; }
            string action = JsonString(payload, "action");
            if (action == null) { action = payload; }        // 纯字符串消息
            if (action == "retry")
            {
                Task ignore = StartAppAsync();
            }
            else if (action == "log")
            {
                OpenLogFolder();
            }
            else if (action == "browser")
            {
                OpenExternal();
            }
            else if (action == "quit")
            {
                Close();
            }
            else if (action == "reload")
            {
                ReloadPage();
            }
            else if (action == "pw")
            {
                SetPassword();
            }
            else if (action == "console")
            {
                NavigateToConsole();
            }
            else if (action == "setpw")
            {
                Task ignore = ApplyPasswordAsync(JsonString(payload, "username"), JsonString(payload, "password"));
            }
        }

        /// <summary>
        /// 从一段 JSON 里取一个字符串字段。只干这一件事，所以不引 JSON 库：
        /// 认转义（\\ \" \n \r \t \/ \uXXXX），认不出就返回 null。
        /// </summary>
        private static string JsonString(string json, string name)
        {
            if (json == null || name == null) { return null; }
            string key = "\"" + name + "\"";
            int at = json.IndexOf(key, StringComparison.Ordinal);
            if (at < 0) { return null; }
            int colon = json.IndexOf(':', at + key.Length);
            if (colon < 0) { return null; }
            int i = colon + 1;
            while (i < json.Length && char.IsWhiteSpace(json[i])) { i++; }
            if (i >= json.Length || json[i] != '"') { return null; }
            StringBuilder builder = new StringBuilder();
            for (i++; i < json.Length; i++)
            {
                char ch = json[i];
                if (ch == '"') { return builder.ToString(); }
                if (ch != '\\') { builder.Append(ch); continue; }
                i++;
                if (i >= json.Length) { break; }
                char esc = json[i];
                if (esc == 'n') { builder.Append('\n'); }
                else if (esc == 'r') { builder.Append('\r'); }
                else if (esc == 't') { builder.Append('\t'); }
                else if (esc == 'b') { builder.Append('\b'); }
                else if (esc == 'f') { builder.Append('\f'); }
                else if (esc == 'u' && i + 4 < json.Length)
                {
                    int code;
                    if (int.TryParse(json.Substring(i + 1, 4), NumberStyles.HexNumber, null, out code))
                    {
                        builder.Append((char)code);
                        i += 4;
                    }
                }
                else { builder.Append(esc); }
            }
            return null;
        }

        /// <summary>日志文件最后几行——出错时贴给人看的那点内容。</summary>
        private string TailLog(int lines)
        {
            try
            {
                string path = Path.Combine(_logDir, "desktop-" + DateTime.Now.ToString("yyyyMMdd") + ".log");
                if (!File.Exists(path)) { return "（日志还没写出来：" + path + "）"; }
                string[] all = File.ReadAllLines(path, Encoding.UTF8);
                int from = Math.Max(0, all.Length - lines);
                return string.Join(Environment.NewLine, all, from, all.Length - from);
            }
            catch (Exception ex) { return "（读日志失败：" + ex.Message + "）"; }
        }

        /// <summary>单文件版第一次启动：把 exe 尾部的 zip 解出来，之后启动直接复用。</summary>
        private async Task UnpackBundledRuntimeAsync()
        {
            SetStatus("正在解出运行时（首次启动约 320 MB）…");
            string root = await Task.Run(delegate
            {
                return BundledRuntime.Ensure(delegate(string message)
                {
                    AppendLog(message);
                    string trimmed = message.Trim();
                    if (trimmed.Length > 0) { SetStatus(trimmed); }
                });
            });
            if (string.IsNullOrEmpty(root))
            {
                // 关键：这里不能把 _singleFile 关掉。关掉之后就按「便携版 + desktop.json」
                // 继续走，最后弹出一句「desktop.json 指向的解释器不存在」——用户根本
                // 不知道发生了什么，还以为单文件版要装环境。
                _runtimeBroken = true;
                AppendLog("[x] 内置运行时解不出来：" + BundledRuntime.Error);
                _failTitle = "运行时没解出来";
                _failLead = "这个 exe 自带运行时，不需要装 Python。这次没解开，"
                    + "多半是杀毒软件拦了、磁盘空间不够，或者目录不能写。点重试可以再解一次。";
                _failDetail = BundledRuntime.Error;
                return;
            }
            _repoRoot = root;
            _packageDir = root;
            _pythonOverride = Path.Combine(root, "py", "python.exe");
            _portable = true;
            _logDir = Path.Combine(root, LogFolderName);
            _runtimeBroken = false;
            AppendLog("[+] 运行时就绪：" + root);
        }

        // ---------------- 日志 ----------------

        private void AppendLog(string line)
        {
            if (_closing) { return; }
            lock (_logLock)
            {
                try
                {
                    string path = Path.Combine(_logDir, "desktop-" + DateTime.Now.ToString("yyyyMMdd") + ".log");
                    Directory.CreateDirectory(_logDir);
                    File.AppendAllText(path, "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + line + Environment.NewLine, Encoding.UTF8);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        /// <summary>
        /// 更新启动页上那行字。窗口里没有状态条也没有日志框了，所以这里只往页面上写；
        /// 页面还没建好时先记住，等页面加载完补上。
        /// </summary>
        private void SetStatus(string text, Color color)
        {
            SetStatus(text);
        }

        private void SetStatus(string text)
        {
            if (_closing) { return; }
            _statusText = text;
            if (InvokeRequired)
            {
                try { BeginInvoke(new Action<string>(SetStatus), text); }
                catch (InvalidOperationException) { }
                return;
            }
            if (_uiPage && _splashLoaded) { PushSplashStatus(text); }
        }

        private void OpenLogFolder()
        {
            try
            {
                Directory.CreateDirectory(_logDir);
                Process.Start("explorer.exe", "/select,\"" + _logDir + "\"");
            }
            catch (Exception ex) { AppendLog("[x] 打不开日志目录：" + ex.Message); }
        }

        // ---------------- 进程与解释器 ----------------

        private string VenvPython()
        {
            return Path.Combine(_packageDir, ".venv", "Scripts", "python.exe");
        }

        /// <summary>跑 bootstrap.py 用的解释器：优先 venv 里的，否则 desktop.json 指定的，最后找系统 Python。</summary>
        private string PickPythonForBootstrap()
        {
            string venv = VenvPython();
            if (File.Exists(venv)) { return venv; }
            if (!string.IsNullOrEmpty(_pythonOverride) && File.Exists(_pythonOverride)) { return _pythonOverride; }
            string fromEnv = Environment.GetEnvironmentVariable("SPIRITSCOUT_PYTHON");
            if (!string.IsNullOrEmpty(fromEnv) && File.Exists(fromEnv)) { return fromEnv; }
            string[] probes = new string[] { "py -3.11", "py -3", "python", "python3" };
            foreach (string probe in probes)
            {
                string version = RunCapture(probe, "-c \"import sys;print(sys.version_info[:2])\"", 15000);
                if (version != null && version.IndexOf("3.1") >= 0) { return probe; }
            }
            return null;
        }

        /// <summary>同步跑一个短命令拿 stdout；失败返回 null。解释器名字里可能带空格（py -3.11）。</summary>
        private static string RunCapture(string exe, string args, int timeoutMs)
        {
            try
            {
                ProcessStartInfo psi = BuildStartInfo(exe, args);
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process proc = Process.Start(psi))
                {
                    string stdout = proc.StandardOutput.ReadToEnd();
                    proc.StandardError.ReadToEnd();
                    if (!proc.WaitForExit(timeoutMs))
                    {
                        try { proc.Kill(); } catch (InvalidOperationException) { }
                        return null;
                    }
                    return proc.ExitCode == 0 ? stdout : null;
                }
            }
            catch (Exception) { return null; }
        }

        private static ProcessStartInfo BuildStartInfo(string exe, string args)
        {
            ProcessStartInfo psi;
            int space = exe.IndexOf(' ');
            if (space > 0)
            {
                // "py -3.11" 这类启动器：程序名和参数得分开传
                psi = new ProcessStartInfo(exe.Substring(0, space), exe.Substring(space + 1) + " " + args);
            }
            else
            {
                psi = new ProcessStartInfo(exe, args);
            }
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            // 便携版自带依赖：别让宿主机 %APPDATA%\Python 里的同名包装进 sys.path
            psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            // 宿主机要是设过 PYTHONHOME / PYTHONPATH / PYTHONSTARTUP，内嵌解释器会被带歪
            // （典型症状：同一个 exe 在别人机器上 import 就崩）。这里一律清掉。
            psi.EnvironmentVariables.Remove("PYTHONHOME");
            psi.EnvironmentVariables.Remove("PYTHONPATH");
            psi.EnvironmentVariables.Remove("PYTHONSTARTUP");
            return psi;
        }

        /// <summary>把一段命令的输出逐行喂给日志框，直到进程退出。</summary>
        private async Task<int> RunStreamingAsync(string exe, string args, string workDir)
        {
            if (exe == null)
            {
                AppendLog("[x] 找不到可用的 Python（需要 3.11+）。装好后重开本程序，或用环境变量 SPIRITSCOUT_PYTHON 指定解释器。");
                return 127;
            }
            ProcessStartInfo psi = BuildStartInfo(exe, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = workDir;
            Process proc = new Process();
            proc.StartInfo = psi;
            proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await Task.Run(delegate { proc.WaitForExit(); });
            int code = proc.ExitCode;
            proc.Dispose();
            return code;
        }

        // ---------------- 环境确认 ----------------

        private string _failTitle = "环境没准备好";
        private string _failLead = "";
        private string _failDetail = "";

        /// <summary>
        /// 服务要用的解释器：先看 .venv，再看 desktop.json 指的内嵌 Python，
        /// 仓库版最后退回系统里的 python / py 启动器。
        /// </summary>
        private sealed class CaptureResult
        {
            public int Code;
            public string Output = "";
        }

        /// <summary>跑一个命令，把 stdout 收下来（不逐行刷日志），失败信息仍进日志。</summary>
        private async Task<CaptureResult> CaptureAsync(string exe, string args, string workDir)
        {
            CaptureResult result = new CaptureResult();
            if (exe == null)
            {
                AppendLog("[x] 找不到可用的 Python（需要 3.11+）。装好后重开本程序，或用环境变量 SPIRITSCOUT_PYTHON 指定解释器。");
                result.Code = 127;
                return result;
            }
            ProcessStartInfo psi = BuildStartInfo(exe, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = workDir;
            Process proc = new Process();
            proc.StartInfo = psi;
            string text = "";
            string err = "";
            try
            {
                proc.Start();
                // 两个流都用同步读，且放到后台线程：在 UI 线程上 ReadToEnd 会卡住窗口，
                // 而同一条流混用同步/异步读会直接抛「不能混合同步操作和异步操作」。
                await Task.Run(delegate
                {
                    text = proc.StandardOutput.ReadToEnd();
                    err = proc.StandardError.ReadToEnd();
                    proc.WaitForExit();
                });
                result.Output = text;
                result.Code = proc.ExitCode;
                if (err.Trim().Length > 0 && result.Code != 0)
                {
                    AppendLog("    " + err.Trim());
                }
            }
            catch (Exception ex)
            {
                AppendLog("[x] 命令跑不起来：" + ex.Message);
                result.Code = 1;
            }
            finally
            {
                try { proc.Dispose(); } catch (Exception) { }
            }
            return result;
        }

        private string PickServerPython()
        {
            string venv = VenvPython();
            if (File.Exists(venv)) { return venv; }
            if (!string.IsNullOrEmpty(_pythonOverride) && File.Exists(_pythonOverride)) { return _pythonOverride; }
            if (_portable) { return null; }
            return PickPythonForBootstrap();
        }

        /// <summary>
        /// 确认「这台机器现在能不能跑起来」。能跑就把解释器返回，跑不了把原因写进
        /// _failTitle/_failLead/_failDetail（错误页原样显示），返回 null。
        /// 全自动：仓库版缺依赖时自己先跑一遍 bootstrap，失败才算环境问题。
        /// </summary>
        private async Task<string> EnsureReadyAsync()
        {
            if (_runtimeBroken)
            {
                _failTitle = "运行时没解出来";
                _failLead = "单文件版自带运行时，不需要装 Python。这次没解开，多半是杀毒软件拦了、磁盘空间不够，或者目录不能写。";
                _failDetail = BundledRuntime.Error;
                return null;
            }
            string python = PickServerPython();
            if (python == null && !_portable)
            {
                AppendLog("[>] 没有现成的解释器，自动跑一遍 bootstrap");
                SetStatus("正在准备依赖（第一次要几分钟，别关窗口）…");
                string boot = PickPythonForBootstrap();
                string script = Path.Combine(_packageDir, "scripts", "bootstrap.py");
                if (boot != null && File.Exists(script))
                {
                    int code = await RunStreamingAsync(boot, "\"" + script + "\" --fix", _repoRoot);
                    AppendLog("[i] bootstrap 退出码 " + code);
                }
                python = PickServerPython();
            }
            if (python == null)
            {
                _failTitle = _portable ? "窗口壳旁边少了运行时" : "找不到能用的 Python";
                _failLead = _portable
                    ? "这个 exe 只是窗口壳，运行时（py\\ 和 configs\\）得跟它放在一起。想双击就用，请下 spiritscout-<版本>-single-win64.exe 那个单文件版。"
                    : "这台机器上没找到装着依赖的 Python 3.11+。装好 Python 后点重试，或用环境变量 SPIRITSCOUT_PYTHON 指定解释器。";
                _failDetail = "程序目录：" + _packageDir + Environment.NewLine + "日志：" + TailLog(12);
                return null;
            }
            AppendLog("[>] 用这个解释器：" + python);
            CaptureResult probe = await CaptureAsync(python,
                "-c \"import sys, spiritscout; print(spiritscout.__version__ + ' | ' + sys.version.split()[0])\"",
                _packageDir);
            string text = probe.Output == null ? "" : probe.Output.Trim();
            if (probe.Code != 0 || text.Length == 0)
            {
                _failTitle = "依赖不完整";
                _failLead = "解释器找到了，但 import spiritscout 失败——运行时目录可能被杀毒软件清过，或者装得不全。点重试会再解一次并重试启动。";
                _failDetail = "解释器：" + python + Environment.NewLine + "退出码：" + probe.Code
                    + Environment.NewLine + text + Environment.NewLine + "--- 日志 ---" + Environment.NewLine + TailLog(12);
                return null;
            }
            AppendLog("[+] 运行时可用：灵枢 " + text);
            return python;
        }

        // ---------------- 服务进程 ----------------

        private static int FreePort(int preferred)
        {
            for (int candidate = preferred; candidate < preferred + 40; candidate++)
            {
                try
                {
                    TcpListener listener = new TcpListener(IPAddress.Loopback, candidate);
                    listener.Start();
                    listener.Stop();
                    return candidate;
                }
                catch (SocketException) { }
            }
            TcpListener any = new TcpListener(IPAddress.Loopback, 0);
            any.Start();
            int port = ((IPEndPoint)any.LocalEndpoint).Port;
            any.Stop();
            return port;
        }

        private async Task<bool> StartServerAsync(string python)
        {
            if (_server != null && !_server.HasExited)
            {
                AppendLog("[i] 服务已经在跑，端口 " + _port);
                NavigateToConsole();
                return true;
            }
            if (python == null)
            {
                _failTitle = "找不到能用的 Python";
                _failLead = "控制台要用 Python 跑起来，但这台机器上没找到可用的解释器。";
                _failDetail = TailLog(12);
                return false;
            }
            KillStaleServer();
            _port = FreePort(_port);
            string config = Path.Combine(_packageDir, "configs", "system.yaml");
            if (!File.Exists(config))
            {
                AppendLog("[!] 没找到 " + config);
                _failTitle = "配置文件缺失";
                _failLead = "控制台要读 configs\\system.yaml，这份运行时里没有——目录可能被杀毒软件清过。重新解压或换个目录再试。";
                _failDetail = "缺：" + config + Environment.NewLine + "程序目录：" + _packageDir;
                return false;
            }

            string args = "-X utf8 -m spiritscout --config configs\\system.yaml --port " + _port;
            ProcessStartInfo psi = BuildStartInfo(python, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = _packageDir;
            psi.EnvironmentVariables["SPIRITSCOUT_SANDBOX_BACKEND"] = "host";
            psi.EnvironmentVariables["SPIRITSCOUT_EXECUTOR__SANDBOX_BACKEND"] = "host";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

            _serverErr = new StringBuilder();
            Process proc = new Process();
            proc.StartInfo = psi;
            proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data == null) { return; }
                AppendLog(e.Data);
                lock (_serverErr) { _serverErr.AppendLine(e.Data); }
            };
            try
            {
                proc.Start();
            }
            catch (Exception ex)
            {
                AppendLog("[x] 起不来：" + ex.Message);
                _failTitle = "控制台起不来";
                _failLead = "解释器找到了，但服务进程没能启动。";
                _failDetail = "命令：" + python + " " + args + Environment.NewLine + ex.Message;
                return false;
            }
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            _server = proc;
            WriteServerPid(proc.Id);
            AppendLog("[>] python " + args);
            SetStatus("正在启动控制台（端口 " + _port + "）…");

            string url = "http://127.0.0.1:" + _port + "/";
            int waited = 0;
            while (waited < 120000)
            {
                if (await ProbeAsync(url))
                {
                    AppendLog("[+] 控制台已就绪：" + url);
                    SetStatus("控制台已就绪");
                    NavigateToConsole();
                    return true;
                }
                if (_server == null || _server.HasExited) { break; }
                await Task.Delay(500);
                waited += 500;
                if (waited % 5000 == 0)
                {
                    SetStatus("正在启动控制台… 已等 " + (waited / 1000) + " 秒");
                }
            }

            string tail;
            lock (_serverErr) { tail = _serverErr.ToString().Trim(); }
            AppendLog("[x] 控制台没起来（等了 " + (waited / 1000) + " 秒）");
            _failTitle = "控制台没起来";
            _failLead = "服务进程启动了，但一直没响应。端口被占、依赖装了一半、或者模型配置有问题都可能这样。";
            _failDetail = "端口：" + _port + Environment.NewLine
                + (tail.Length > 0 ? tail : "（子进程没有输出）") + Environment.NewLine
                + "--- 日志 ---" + Environment.NewLine + TailLog(20);
            return false;
        }

        /// <summary>
        /// 上次窗口被强杀/崩了的时候，控制台进程会留着占端口，下回启动就会莫名其妙换端口。
        /// 这里留一个 pid 文件，启动时先把那一个（只认 -m spiritscout 的）收掉。
        /// </summary>
        private string ServerPidFile()
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SpiritScout");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "server.pid");
        }

        private void WriteServerPid(int pid)
        {
            try { File.WriteAllText(ServerPidFile(), pid.ToString()); }
            catch (Exception) { }
        }

        private void ClearServerPid()
        {
            try { File.Delete(ServerPidFile()); }
            catch (Exception) { }
        }

        private void KillStaleServer()
        {
            try
            {
                string path = ServerPidFile();
                if (!File.Exists(path)) { return; }
                int pid;
                if (!int.TryParse(File.ReadAllText(path).Trim(), out pid)) { ClearServerPid(); return; }
                Process stale = Process.GetProcessById(pid);
                // 只认 python 进程：pid 会被系统复用，别误杀别人的东西
                if (stale != null && !stale.HasExited
                    && stale.ProcessName.StartsWith("python", StringComparison.OrdinalIgnoreCase))
                {
                    AppendLog("[i] 收掉上次没退干净的控制台进程 " + pid);
                    ProcessStartInfo kill = new ProcessStartInfo("taskkill", "/pid " + pid + " /t /f");
                    kill.UseShellExecute = false;
                    kill.CreateNoWindow = true;
                    Process.Start(kill);
                    stale.WaitForExit(5000);
                }
            }
            catch (Exception) { }
            ClearServerPid();
        }

        private static async Task<bool> WaitForServerAsync(int port, int timeoutMs)
        {
            string url = "http://127.0.0.1:" + port + "/";
            int waited = 0;
            while (waited < timeoutMs)
            {
                if (await ProbeAsync(url)) { return true; }
                await Task.Delay(500);
                waited += 500;
            }
            return false;
        }

        private static async Task<bool> ProbeAsync(string url)
        {
            return await Task.Run(delegate
            {
                try
                {
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                    request.Timeout = 2000;
                    request.Method = "GET";
                    request.Proxy = null;
                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    {
                        return (int)response.StatusCode >= 200 && (int)response.StatusCode < 500;
                    }
                }
                catch (Exception) { return false; }
            });
        }

        private void StopServer(bool userAsked)
        {
            Process proc = _server;
            _server = null;
            ClearServerPid();
            if (proc == null) { return; }
            try
            {
                if (!proc.HasExited)
                {
                    // 子进程树里可能有沙箱与工具子进程，按树杀，别留孤儿
                    ProcessStartInfo kill = new ProcessStartInfo("taskkill",
                        "/pid " + proc.Id + " /t /f");
                    kill.UseShellExecute = false;
                    kill.CreateNoWindow = true;
                    Process.Start(kill);
                    proc.WaitForExit(8000);
                }
            }
            catch (Exception ex) { AppendLog("[!] 停服务时出错：" + ex.Message); }
            if (userAsked) { AppendLog("[i] 已停止控制台"); }
        }

        // ---------------- 内嵌浏览器 ----------------

        private async Task InitWebViewAsync()
        {
            if (_web == null)
            {
                _webReady = false;
                AppendLog("[!] 没有内嵌浏览器控件：" + (Runtime.LastError ?? "控件创建失败"));
                ShowBrowserFallback("内嵌浏览器控件没建起来（"
                    + (Runtime.LastError ?? "WebView2 的三个 DLL 解不出来") + "）。");
                return;
            }
            // 先确认这台机器上到底有没有 WebView2 运行时：没有的话再试也是白试，
            // 直接把界面交给系统浏览器，别去弹「缺组件」那种让人以为程序坏了的框。
            string runtimeVersion = null;
            try { runtimeVersion = CoreWebView2Environment.GetAvailableBrowserVersionString(); }
            catch (Exception) { }
            if (string.IsNullOrEmpty(runtimeVersion))
            {
                _webReady = false;
                AppendLog("[!] 这台机器没装 Edge WebView2 运行时，改用系统浏览器承载界面");
                ShowBrowserFallback("这台机器没装 Microsoft Edge WebView2 运行时，窗口里画不了页面；"
                    + "控制台照样能在浏览器里用，是同一份页面，排版样式完全一致。");
                return;
            }
            try
            {
                // 用户数据目录指定到仓库外：默认会落在 exe 旁边（灵枢桌面版.exe.WebView2/），
                // 把工作区弄脏，只读安装目录下还会直接失败。
                // 这一步最容易在「别人的机子」上出问题：上一份浏览器进程没退干净，
                // 或者 profile 被杀毒软件摸过，WebView2 会报 0x800700AA（资源在使用中）。
                // 处理办法是自愈：把这份 profile 挪开 → 重建控件 → 用干净的目录再来一次。
                bool started = false;
                string dir = UserDataDir();
                string failure = null;
                // 逐级换目录，每一级都用新控件（失败过的控件再初始化只会甩 E_UNEXPECTED）：
                //   1. 常用的那份 profile；
                //   2. 带进程号的兄弟目录——上一次的 msedgewebview2.exe 没退干净时，
                //      常用目录会被独占（0x800700AA），换一个就绕开了；
                //   3. 临时目录，最后再赌一次。
                string pid = Process.GetCurrentProcess().Id.ToString();
                string[] attempts = new string[]
                {
                    dir,
                    dir + "-" + pid,
                    Path.Combine(Path.GetTempPath(), "SpiritScout-webview2-" + pid),
                };
                for (int i = 0; i < attempts.Length && !started; i++)
                {
                    string current = attempts[i];
                    if (i > 0 && !RecreateWebView()) { break; }
                    try
                    {
                        await EnsureBrowserAsync(current);
                        started = true;
                        if (i > 0) { AppendLog("[+] 换到备用浏览器数据目录起来了：" + current); }
                    }
                    catch (Exception ex)
                    {
                        failure = ex.Message;
                        AppendLog("[!] 浏览器数据目录起不来（" + current + "）：" + ex.Message);
                    }
                }
                if (!started)
                {
                    throw new InvalidOperationException(failure ?? "浏览器数据目录全都起不来", null);
                }
                _web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                InstallShortcutBridge();
                _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                _web.CoreWebView2.Settings.IsZoomControlEnabled = true;
                try
                {
                    // 再设一次：控件底色有时候要等 controller 建好才生效
                    _web.DefaultBackgroundColor = Color.FromArgb(246, 247, 249);
                }
                catch (Exception) { }
                _web.CoreWebView2.WebMessageReceived += delegate(object sender, CoreWebView2WebMessageReceivedEventArgs e)
                {
                    // 两种消息都收：错误页那些按钮发的是纯字符串，密码对话框发的是对象。
                    string payload = "";
                    try { payload = e.TryGetWebMessageAsString(); }
                    catch (Exception) { }
                    if (string.IsNullOrEmpty(payload))
                    {
                        try { payload = e.WebMessageAsJson; }
                        catch (Exception) { }
                    }
                    HandleUiAction(payload);
                };
                _web.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
                {
                    if (!e.IsSuccess)
                    {
                        AppendLog("[!] 页面加载失败：" + e.WebErrorStatus);
                        return;
                    }
                    if (_uiPage && _uiHtmlShown)
                    {
                        // 启动页/错误页刚画出来：把这期间攒下的状态补上去
                        _splashLoaded = true;
                        PushSplashStatus(_statusText);
                        return;
                    }
                    string title = "";
                    try { title = _web.CoreWebView2.DocumentTitle; } catch (Exception) { }
                    AppendLog("[+] 页面已加载：" + (title.Length > 0 ? title : "（无标题）"));
                };
                _webReady = true;
                AppendLog("[+] 内嵌浏览器就绪（WebView2 " + _web.CoreWebView2.Environment.BrowserVersionString + "）");
            }
            catch (Exception ex)
            {
                _webReady = false;
                AppendLog("[!] 内嵌浏览器初始化失败：" + ex.Message);
                ShowBrowserFallback(DescribeBrowserFailure(ex));
            }
        }

        /// <summary>
        /// 内嵌浏览器用不了时的兜底：窗口里画一张跟控制台同色的提示卡，
        /// 控制台本身交给系统浏览器（Edge 的 --app 窗口，没有地址栏）。
        /// 不给用户看「缺少内嵌浏览器组件」那种弹框——他要的是那份页面，
        /// 页面在浏览器里是同一份，排版样式完全一致。
        /// </summary>
        private void ShowBrowserFallback(string reason)
        {
            _webReady = false;
            if (_fallbackShown && _canvas != null && _canvas.Controls.Count > 0) { return; }
            _fallbackShown = true;
            AppendLog("[i] 界面改由系统浏览器承载：" + reason);
            try
            {
                BuildFallbackPage(reason);
            }
            catch (Exception ex)
            {
                AppendLog("[!] 兜底页画不出来：" + ex.Message);
            }
            // 服务已经起来的话，直接把控制台在浏览器里打开；没起来就等
            // NavigateToConsole()（它看到 _webReady=false 会走 OpenExternal）。
            if (_server != null && !_server.HasExited) { OpenExternal(); }
        }

        /// <summary>兜底页：一张白卡片 + 主按钮，配色/字号跟控制台那套令牌对齐。</summary>
        private void BuildFallbackPage(string reason)
        {
            Panel host = _canvas;
            if (host == null) { return; }
            host.SuspendLayout();
            host.Controls.Clear();

            Panel page = new Panel();
            page.Dock = DockStyle.Fill;
            page.BackColor = Color.FromArgb(246, 248, 250);   // --bg
            page.Padding = new Padding(28);

            Panel card = new Panel();
            card.Dock = DockStyle.Top;
            card.Height = 232;
            card.BackColor = Color.White;                     // --surface
            card.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen pen = new Pen(Color.FromArgb(216, 222, 228)))   // --line
                {
                    e.Graphics.DrawRectangle(pen, 0, 0, card.Width - 1, card.Height - 1);
                }
            };

            Label title = new Label();
            title.Text = "已在浏览器里打开控制台";
            title.Font = new Font("Microsoft YaHei UI", 12.5f, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(31, 35, 40);     // --ink
            title.AutoSize = true;
            title.Location = new Point(22, 20);

            Label lead = new Label();
            lead.Text = "窗口里的内嵌浏览器这次没起来，控制台交给系统浏览器打开了——就是那份页面，排版和样式跟窗口里完全一致。";
            lead.Font = new Font("Microsoft YaHei UI", 9.5f);
            lead.ForeColor = Color.FromArgb(89, 99, 110);     // --ink-2
            lead.AutoSize = false;
            lead.Size = new Size(card.Width > 120 ? card.Width - 44 : 420, 44);
            lead.Location = new Point(22, 56);
            lead.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;

            Label detail = new Label();
            detail.Text = reason;
            detail.Font = new Font("Consolas", 8.5f);
            detail.ForeColor = Color.FromArgb(129, 139, 152);  // --ink-3
            detail.AutoSize = false;
            detail.Size = new Size(lead.Width, 58);
            detail.Location = new Point(22, 104);
            detail.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;

            Button again = MakeFlatButton("再打开一次", true, 104);
            again.Location = new Point(22, 176);
            again.Click += delegate { OpenExternal(); };

            Button retry = MakeFlatButton("重试内嵌浏览器", false, 128);
            retry.Location = new Point(134, 176);
            retry.Click += delegate { RetryEmbedded(); };

            Button quit = MakeFlatButton("退出", false, 76);
            quit.Location = new Point(270, 176);
            quit.Click += delegate { Close(); };

            card.Controls.Add(title);
            card.Controls.Add(lead);
            card.Controls.Add(detail);
            card.Controls.Add(again);
            card.Controls.Add(retry);
            card.Controls.Add(quit);
            page.Controls.Add(card);
            host.Controls.Add(page);
            host.ResumeLayout();
        }

        /// <summary>控制台按钮那套尺寸：32px 高、6px 圆角、主按钮 #0969da。</summary>
        private static Button MakeFlatButton(string text, bool primary, int width)
        {
            Button button = new Button();
            button.Text = text;
            button.AutoSize = false;
            button.Size = new Size(width, 32);
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.BorderColor = primary
                ? Color.FromArgb(7, 87, 186) : Color.FromArgb(188, 196, 205);
            button.BackColor = primary ? Color.FromArgb(9, 105, 218) : Color.White;
            button.ForeColor = primary ? Color.White : Color.FromArgb(31, 35, 40);
            button.Font = new Font("Microsoft YaHei UI", 9f, primary ? FontStyle.Bold : FontStyle.Regular);
            button.UseVisualStyleBackColor = false;
            button.Cursor = Cursors.Hand;
            return button;
        }

        /// <summary>兜底页上的「重试内嵌浏览器」：重建控件再来一次，成功就切回窗口里。</summary>
        private async void RetryEmbedded()
        {
            AppendLog("[>] 再试一次内嵌浏览器");
            _fallbackShown = false;
            try
            {
                if (_canvas != null) { _canvas.Controls.Clear(); }
                if (!RecreateWebView())
                {
                    ShowBrowserFallback("浏览器控件重建失败，还是用浏览器。");
                    return;
                }
                if (_canvas != null) { _canvas.Controls.Add(_web); }
                await InitWebViewAsync();
                if (_webReady) { NavigateToConsole(); }
            }
            catch (Exception ex)
            {
                AppendLog("[!] 重试失败：" + ex.Message);
                ShowBrowserFallback(DescribeBrowserFailure(ex));
            }
        }

        /// <summary>把 WebView2 的异常翻成人话，写进兜底卡片。</summary>
        private static string DescribeBrowserFailure(Exception ex)
        {
            string text = ex == null ? "" : ex.ToString();
            if (text.IndexOf("0x800700AA", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("使用中", StringComparison.Ordinal) >= 0
                || text.IndexOf("正在使用", StringComparison.Ordinal) >= 0
                || text.IndexOf("being used", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "浏览器数据目录被另一个灵枢窗口或残留的 WebView2 进程占着（0x800700AA）。"
                    + "关掉多余的窗口再按「重试内嵌浏览器」；不重试也没关系，浏览器里那一份一样能用。";
            }
            if (text.IndexOf("0x8000FFFF", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "浏览器进程没能初始化（0x8000FFFF），多半是上一次的进程没退干净。"
                    + "按「重试内嵌浏览器」再试一次即可。";
            }
            return ex == null ? "内嵌浏览器没起来。" : ex.Message;
        }

        /// <summary>把起不来的 profile 挪到一边（不删，万一还要查），返回新位置。</summary>
        private string QuarantineProfile(string dir)
        {
            try
            {
                if (!Directory.Exists(dir)) { return null; }
                string target = dir + ".broken-" + DateTime.Now.ToString("yyyyMMdd-HHmmss");
                Directory.Move(dir, target);
                return target;
            }
            catch (Exception ex)
            {
                AppendLog("[!] profile 挪不动：" + ex.Message);
                return null;
            }
        }

        /// <summary>换一个新的浏览器控件：失败过一次的控件再初始化会直接摊手（E_UNEXPECTED）。</summary>
        private bool RecreateWebView()
        {
            try
            {
                Control parent = _web == null ? null : _web.Parent;
                if (_web != null)
                {
                    if (parent != null) { parent.Controls.Remove(_web); }
                    try { _web.Dispose(); } catch (Exception) { }
                    _web = null;
                }
                Control fresh = CreateWebView();
                if (_web == null) { return false; }
                if (parent != null)
                {
                    parent.Controls.Add(fresh);
                    fresh.BringToFront();
                }
                try { _web.DefaultBackgroundColor = Color.FromArgb(246, 247, 249); }
                catch (Exception) { }
                return true;
            }
            catch (Exception ex)
            {
                AppendLog("[!] 重建浏览器控件失败：" + ex.Message);
                return false;
            }
        }

        /// <summary>用指定的用户数据目录把浏览器拉起来。</summary>
        private async Task EnsureBrowserAsync(string userDataDir)
        {
            CoreWebView2Environment environment =
                await CoreWebView2Environment.CreateAsync(null, userDataDir, BrowserOptions());
            await _web.EnsureCoreWebView2Async(environment);
        }

        /// <summary>
        /// 调试口：只有设了 SPIRITSCOUT_WEBVIEW_DEBUG_PORT 才给 WebView2 开 CDP。
        /// 开着它就能用 Playwright/DevTools 连上真窗口，量字号、圆角、有没有溢出，
        /// 比拿 file:// 打开同一份 HTML 猜要靠谱——WebView2 的字体回退和缩放跟外面不一样。
        /// 平时不设这个变量，就不加任何浏览器参数。
        /// </summary>
        private CoreWebView2EnvironmentOptions BrowserOptions()
        {
            string raw = Environment.GetEnvironmentVariable("SPIRITSCOUT_WEBVIEW_DEBUG_PORT");
            int port;
            if (string.IsNullOrEmpty(raw) || !int.TryParse(raw, out port) || port < 1024 || port > 65535)
            {
                return null;
            }
            CoreWebView2EnvironmentOptions options = new CoreWebView2EnvironmentOptions();
            options.AdditionalBrowserArguments =
                "--remote-debugging-port=" + port.ToString(System.Globalization.CultureInfo.InvariantCulture);
            AppendLog("[i] 已开调试口 http://127.0.0.1:" + port.ToString() + "（CDP，可在真窗口里量样式）");
            return options;
        }

        /// <summary>WebView2 的用户数据目录：跟解压目录一样三级回退，别写进工作区。</summary>
        private string UserDataDir()
        {
            // 构建脚本的冒烟测试会塞一个临时目录进来：不然它和用户正在开的窗口抢同一份
            // profile，WebView2 直接报 0x800700AA（资源在使用中），看着像启动失败。
            string custom = Environment.GetEnvironmentVariable("SPIRITSCOUT_WEBVIEW_DIR");
            if (!string.IsNullOrEmpty(custom))
            {
                try
                {
                    Directory.CreateDirectory(custom);
                    return custom;
                }
                catch (Exception) { }
            }
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                string preferred = Path.Combine(localAppData, "SpiritScout", "webview2");
                try
                {
                    Directory.CreateDirectory(preferred);
                    return preferred;
                }
                catch (Exception) { }
            }
            string beside = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "灵枢桌面版-lib", "webview2");
            try
            {
                Directory.CreateDirectory(beside);
                return beside;
            }
            catch (Exception) { }
            string temp = Path.Combine(Path.GetTempPath(), "SpiritScout-webview2");
            Directory.CreateDirectory(temp);
            return temp;
        }
        private void NavigateToConsole()
        {
            string url = "http://127.0.0.1:" + _port + "/";
            if (_webReady)
            {
                _uiPage = false;
                _splashLoaded = false;
                _uiHtmlShown = false;
                _web.Source = new Uri(url);
                AppendLog("[>] 打开 " + url);
            }
            else
            {
                OpenExternal();
            }
        }

        private void ReloadPage()
        {
            if (_webReady && _web.CoreWebView2 != null) { _web.CoreWebView2.Reload(); }
        }

        private void OpenExternal()
        {
            string url = "http://127.0.0.1:" + _port + "/";
            try
            {
                // Edge 的 --app 模式：独立窗口、没有地址栏与标签页，最接近「软件」的样子
                string edge = FindEdge();
                if (edge != null)
                {
                    Process.Start(new ProcessStartInfo(edge, "--app=" + url) { UseShellExecute = false });
                }
                else
                {
                    Process.Start(url);
                }
            }
            catch (Exception ex) { AppendLog("[x] 打不开浏览器：" + ex.Message); }
        }

        private static string FindEdge()
        {
            string[] candidates = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "Edge", "Application", "msedge.exe"),
            };
            foreach (string path in candidates)
            {
                if (File.Exists(path)) { return path; }
            }
            return null;
        }

        // ---------------- 管理员密码 ----------------

        /// <summary>
        /// 密码在窗口里设：直接画一张和控制台同款的表单，不再弹一个黑色控制台窗口
        /// 让人在里面看不到自己在输什么。收完交给 CLI 写库（只存 scrypt 哈希）。
        /// </summary>
        private void SetPassword()
        {
            if (!_webReady || _web.CoreWebView2 == null)
            {
                AppendLog("[!] 内嵌浏览器没起来，打不开密码界面；日志里有命令行用法。");
                return;
            }
            string html = ReadUiHtml("dialog.html");
            if (html == null) { return; }
            _uiPage = true;
            _uiHtmlShown = false;
            _splashLoaded = false;
            _web.CoreWebView2.NavigateToString(html);
            AppendLog("[>] 打开设置管理员密码的界面");
        }

        /// <summary>跑一条命令、把一行文字喂给它的 stdin，收 stdout/stderr。</summary>
        private async Task<CaptureResult> RunWithInputAsync(string exe, string args, string workDir, string input)
        {
            CaptureResult result = new CaptureResult();
            ProcessStartInfo psi = BuildStartInfo(exe, args);
            psi.RedirectStandardInput = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = workDir;
            Process proc = new Process();
            proc.StartInfo = psi;
            string text = "";
            string err = "";
            try
            {
                proc.Start();
                await Task.Run(delegate
                {
                    try
                    {
                        proc.StandardInput.WriteLine(input == null ? "" : input);
                        proc.StandardInput.Close();
                    }
                    catch (Exception) { }
                    text = proc.StandardOutput.ReadToEnd();
                    err = proc.StandardError.ReadToEnd();
                    proc.WaitForExit();
                });
                result.Code = proc.ExitCode;
                result.Output = (text + (err.Length > 0 ? Environment.NewLine + err : "")).Trim();
            }
            catch (Exception ex)
            {
                result.Code = 1;
                result.Output = "命令跑不起来：" + ex.Message;
            }
            finally
            {
                try { proc.Dispose(); } catch (Exception) { }
            }
            return result;
        }

        /// <summary>把写入结果讲回给对话框（成功/失败都留在同一张页面上）。</summary>
        private async Task ApplyPasswordAsync(string username, string password)
        {
            string python = PickServerPython();
            if (python == null)
            {
                PushDialogResult(false, "这台机器上找不到可用的 Python，写不了管理库。");
                return;
            }
            string user = username == null ? "" : username.Trim();
            string args = "-X utf8 -m spiritscout --set-admin-password --password-stdin";
            if (user.Length > 0) { args += " --admin-username \"" + user + "\""; }
            AppendLog("[>] 写入管理员密码（只存哈希）");
            CaptureResult run = await RunWithInputAsync(python, args, _packageDir, password);
            bool ok = run.Code == 0;
            string message = run.Output.Length > 0
                ? run.Output
                : (ok ? "密码已保存，下次登录用新密码。" : "写入失败（退出码 " + run.Code + "）。");
            if (ok && password != null && password.Length == 0)
            {
                message = "密码为空，已按「不设密码」处理（控制台登录保持关闭）。";
            }
            AppendLog((ok ? "[+] " : "[x] ") + message.Replace(Environment.NewLine, " "));
            PushDialogResult(ok, message);
        }

        private void PushDialogResult(bool ok, string message)
        {
            try
            {
                if (_webReady && _web.CoreWebView2 != null)
                {
                    string script = "window.ssResult ? window.ssResult(" + (ok ? "true" : "false") + ", "
                        + JsString(message) + ") : 0;";
                    _web.CoreWebView2.ExecuteScriptAsync(script);
                }
            }
            catch (Exception ex) { AppendLog("[!] 回写结果失败：" + ex.Message); }
        }

        // ---------------- 收尾 ----------------

        private void OnClosing(object sender, FormClosingEventArgs e)
        {
            _closing = true;
            StopServer(false);
        }
    }
}
