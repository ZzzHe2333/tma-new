// Read-only Authenticode policy probe. Does not add trust anchors or certificates.
using System;
using System.Runtime.InteropServices;

namespace ZzzHe.Release {
    public static class WinTrustProbe {
        [StructLayout(LayoutKind.Sequential)]
        private struct FileInfo {
            public uint Size;
            public IntPtr Path, File, Subject;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct TrustData {
            public uint Size;
            public IntPtr Policy, Client;
            public uint UI, Revocation, Choice;
            public IntPtr File;
            public uint StateAction;
            public IntPtr State, URL;
            public uint Flags, Context;
            public IntPtr SignatureSettings;
        }
        [DllImport("wintrust.dll", ExactSpelling = true, PreserveSig = true)]
        private static extern uint WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);

        public static uint Verify(string path) {
            var action = new Guid("00AAC56B-CD44-11D0-8CC2-00C04FC295EE");
            IntPtr pathPointer = Marshal.StringToCoTaskMemUni(System.IO.Path.GetFullPath(path));
            IntPtr filePointer = IntPtr.Zero;
            var data = new TrustData();
            try {
                var file = new FileInfo { Size = (uint)Marshal.SizeOf(typeof(FileInfo)), Path = pathPointer };
                filePointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(FileInfo)));
                Marshal.StructureToPtr(file, filePointer, false);
                data.Size = (uint)Marshal.SizeOf(typeof(TrustData));
                data.UI = 2; // WTD_UI_NONE
                data.Choice = 1; // WTD_CHOICE_FILE, embedded file signature
                data.File = filePointer;
                data.StateAction = 1; // WTD_STATEACTION_VERIFY
                data.Flags = 0x1000; // WTD_CACHE_ONLY_URL_RETRIEVAL, no network access
                return WinVerifyTrust(new IntPtr(-1), ref action, ref data);
            } finally {
                if (data.State != IntPtr.Zero) {
                    data.StateAction = 2; // WTD_STATEACTION_CLOSE
                    WinVerifyTrust(new IntPtr(-1), ref action, ref data);
                }
                if (filePointer != IntPtr.Zero) Marshal.FreeHGlobal(filePointer);
                Marshal.FreeCoTaskMem(pathPointer);
            }
        }
    }
}
