using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("自动铃声系统")]
[assembly: AssemblyDescription("自动铃声系统桌面启动器")]
[assembly: AssemblyProduct("自动铃声系统")]
[assembly: AssemblyCompany("AutoBell")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class AutoBellLauncher
{
    [STAThread]
    private static void Main(string[] args)
    {
        string directory = AppDomain.CurrentDomain.BaseDirectory;
        string executable = Path.Combine(directory, "AutoBellDesktop.exe");
        if (!File.Exists(executable))
        {
            MessageBox.Show(
                "找不到 AutoBellDesktop.exe，请重新安装自动铃声系统。",
                "自动铃声系统",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        string arguments = "--no-sandbox";
        if (args.Length > 0)
        {
            arguments += " " + string.Join(" ", args);
        }

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = arguments,
                WorkingDirectory = directory,
                UseShellExecute = false,
            };
            Process process = Process.Start(startInfo);
            Thread.Sleep(1800);
            if (process != null && process.HasExited && process.ExitCode != 0)
            {
                MessageBox.Show(
                    "自动铃声系统启动失败，请查看 AutoBellData\\logs 下的日志。",
                    "自动铃声系统",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "自动铃声系统启动失败：\n" + error.Message,
                "自动铃声系统",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }
}
