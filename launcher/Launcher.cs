// 律法夕惕者 Xitilex — 啟動程式／安裝程式（同一份原始碼，編譯時以 INSTALLER 區分）
//   律法夕惕者.exe：以無主控台的 pythonw 執行 run.py，開出原生視窗
//   安裝.exe      ：在主控台執行 install.py，顯示安裝進度
// 只用 C# 5 語法（Windows 內建的 csc.exe 只支援到 C# 5）。
// © 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("律法夕惕者 Xitilex")]
[assembly: System.Reflection.AssemblyProduct("律法夕惕者 Xitilex")]
[assembly: System.Reflection.AssemblyCopyright("© 2026 無名小律師（楊朝淵律師）")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Launcher
{
    const string Title = "律法夕惕者 Xitilex";

    [STAThread]
    static int Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
#if INSTALLER
        string script = Path.Combine(dir, "install.py");
        bool windowed = false;
#else
        string script = Path.Combine(dir, "run.py");
        bool windowed = true;
#endif
        if (!File.Exists(script))
        {
            Fail("找不到 " + Path.GetFileName(script) + "。\n請確認雲端硬碟已經同步完「律法夕惕者 Xitilex」資料夾。");
            return 1;
        }

        string[] py = FindPython(windowed);
        if (py == null)
        {
            Fail("找不到 Python。\n請先安裝 Python 3（python.org），再執行資料夾裡的「安裝」。");
            return 1;
        }

        StringBuilder a = new StringBuilder();
        if (py[1].Length > 0) a.Append(py[1]).Append(' ');
        a.Append(Quote(script));
        foreach (string s in args) a.Append(' ').Append(Quote(s));

        ProcessStartInfo psi = new ProcessStartInfo(py[0], a.ToString());
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        psi.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";   // 不在雲端硬碟裡產生 __pycache__
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try
        {
            Process p = Process.Start(psi);
#if INSTALLER
            p.WaitForExit();
            Console.WriteLine();
            Console.Write("按 Enter 關閉這個視窗…");
            Console.ReadLine();
#endif
        }
        catch (Exception e)
        {
            Fail("無法啟動 Python：" + e.Message);
            return 1;
        }
        return 0;
    }

    // 回傳 {執行檔, 前置參數}
    static string[] FindPython(bool windowed)
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string exe = windowed ? "pythonw.exe" : "python.exe";

        // 1. 安裝程式記下的路徑（%LOCALAPPDATA%\casedesk\local.json）
        string cfg = Path.Combine(local, "casedesk", "local.json");
        if (File.Exists(cfg))
        {
            try
            {
                Match m = Regex.Match(File.ReadAllText(cfg, Encoding.UTF8),
                                      "\"" + (windowed ? "pythonw" : "python") + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
                if (m.Success)
                {
                    string p = Regex.Unescape(m.Groups[1].Value);
                    if (File.Exists(p)) return new string[] { p, "" };
                }
            }
            catch { }
        }

        // 2. 常見的安裝位置
        List<string> cands = new List<string>();
        cands.Add(Path.Combine(local, @"Python\bin", exe));
        string progs = Path.Combine(local, "Programs\\Python");
        if (Directory.Exists(progs))
        {
            string[] ds = Directory.GetDirectories(progs, "Python3*");
            Array.Sort(ds); Array.Reverse(ds);
            foreach (string d in ds) cands.Add(Path.Combine(d, exe));
        }
        foreach (string c in cands) if (File.Exists(c)) return new string[] { c, "" };

        // 3. Python 啟動器（pyw／py -3）
        string launcher = windowed ? "pyw.exe" : "py.exe";
        string winDir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        foreach (string d in new string[] { winDir, Path.Combine(local, "Microsoft\\WindowsApps") })
        {
            string p = Path.Combine(d, launcher);
            if (File.Exists(p)) return new string[] { p, "-3" };
        }
        return null;
    }

    static string Quote(string s)
    {
        return "\"" + s.Replace("\"", "\\\"") + "\"";
    }

    static void Fail(string msg)
    {
#if INSTALLER
        Console.WriteLine(msg);
        Console.Write("按 Enter 關閉…");
        Console.ReadLine();
#else
        MessageBox.Show(msg, Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
#endif
    }
}
