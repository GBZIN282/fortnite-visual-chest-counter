/*
 * Fortnite Visual Chest Counter - launcher ("Fortnite Visual Chest Counter.exe").
 *
 * Its only job: start the desktop app with the official, signed python.org runtime shipped next to it,
 *
 *     runtime\python\pythonw.exe -m fortnite_chest_counter.gui [the arguments given to this program]
 *
 * in the program folder, and exit. No network, no registry, no elevation.
 * If the runtime is missing (usually: started from inside the zip), it says so in a message box.
 *
 * Before that, if an update was interrupted (.update\transaction.json exists), it runs the update helper's recovery with the helper's
 * OWN copy of Python, so a new version that cannot start at all can still be undone. All the recovery logic is in install_helper.py;
 * the only thing done here is the last resort, for when the helper itself cannot run: moving the previous runtime back.
 *
 * Built by packaging/build_release.py:  windres (icon, version info, manifest) + gcc -O2 -s -mwindows.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

#define APP_NAME L"Fortnite Visual Chest Counter"
#define LONG_PATH 32768
#define HELPER_BUSY 3           /* install_helper.py: EXIT_BUSY  */
#define HELPER_STUCK 4          /* install_helper.py: EXIT_STUCK */
#define HELPER_WAIT_MS 180000

static wchar_t folder[LONG_PATH], python[LONG_PATH], command[LONG_PATH + 1024];
static wchar_t journal[LONG_PATH], helper[LONG_PATH], helper_folder[LONG_PATH], helper_command[2 * LONG_PATH];
static wchar_t runtime[LONG_PATH], old_runtime[LONG_PATH], old_python[LONG_PATH];

static void fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, APP_NAME, MB_OK | MB_ICONERROR);
}

static int exists(const wchar_t *path)
{
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

static void join(wchar_t *target, const wchar_t *tail)
{
    wcscpy(target, folder);
    wcscat(target, tail);
}

/* Returns 0 to carry on and start the app, 1 to stop (the user has been told why). */
static int finish_interrupted_update(void)
{
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    DWORD code = 0;

    if (wcslen(folder) > 16000)
        return 0;
    join(journal, L"\\.update\\transaction.json");
    join(helper, L"\\.update\\helper\\python\\pythonw.exe");
    join(helper_folder, L"\\.update\\helper");
    if (exists(journal) && exists(helper)) {
        wcscpy(helper_command, L"\"");
        wcscat(helper_command, helper);
        wcscat(helper_command, L"\" -B -m install_helper recover \"");
        wcscat(helper_command, folder);
        wcscat(helper_command, L"\"");
        ZeroMemory(&startup, sizeof startup);
        startup.cb = sizeof startup;
        ZeroMemory(&process, sizeof process);
        if (CreateProcessW(helper, helper_command, NULL, NULL, FALSE, 0, NULL, helper_folder, &startup, &process)) {
            CloseHandle(process.hThread);
            if (WaitForSingleObject(process.hProcess, HELPER_WAIT_MS) != WAIT_OBJECT_0)
                code = HELPER_BUSY;
            else
                GetExitCodeProcess(process.hProcess, &code);
            CloseHandle(process.hProcess);
            if (code == HELPER_BUSY) {
                MessageBoxW(NULL, L"An update is being installed. The app will open by itself when it has finished.",
                            APP_NAME, MB_OK | MB_ICONINFORMATION);
                return 1;
            }
            if (code == HELPER_STUCK) {
                fail(L"An update could not be finished because a file in the program folder is in use.\n\n"
                     L"Close anything using that folder, or restart the PC, and then open the app again. Your counts are safe.");
                return 1;
            }
        }
    }
    join(runtime, L"\\runtime");
    join(old_runtime, L"\\.update\\old\\runtime");
    join(old_python, L"\\.update\\old\\runtime\\python\\pythonw.exe");
    if (!exists(python) && exists(old_python) && !exists(runtime))
        MoveFileW(old_runtime, runtime);
    return 0;
}

/* The command line after the program name (same splitting rule as CommandLineToArgvW for argv[0]). */
static const wchar_t *arguments(const wchar_t *line)
{
    int quoted = 0;
    while (*line && (quoted || (*line != L' ' && *line != L'\t'))) {
        if (*line == L'"')
            quoted = !quoted;
        line++;
    }
    while (*line == L' ' || *line == L'\t')
        line++;
    return line;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR ignored, int show)
{
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    const wchar_t *args;
    wchar_t message[600];
    wchar_t *slash;
    DWORD length;

    (void)instance; (void)previous; (void)ignored; (void)show;

    length = GetModuleFileNameW(NULL, folder, LONG_PATH);
    if (length == 0 || length >= LONG_PATH) {
        fail(L"Could not find the program folder.");
        return 1;
    }
    slash = wcsrchr(folder, L'\\');
    if (slash)
        *slash = L'\0';

    if (wcslen(folder) + 40 >= LONG_PATH) {
        fail(L"The program folder path is too long. Move the folder somewhere shorter, for example your Desktop.");
        return 1;
    }
    wcscpy(python, folder);
    wcscat(python, L"\\runtime\\python\\pythonw.exe");
    if (finish_interrupted_update())
        return 0;
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fail(L"The program files were not found next to this file.\n\n"
             L"Please extract the WHOLE zip file first (right-click the zip, \"Extract All\"), then open "
             APP_NAME L" from the extracted folder.");
        return 1;
    }

    args = arguments(GetCommandLineW());
    if (wcslen(python) + wcslen(args) + 64 >= LONG_PATH + 1024) {
        fail(L"The command line is too long.");
        return 1;
    }
    wcscpy(command, L"\"");
    wcscat(command, python);
    wcscat(command, L"\" -m fortnite_chest_counter.gui");
    if (*args) {
        wcscat(command, L" ");
        wcscat(command, args);
    }

    ZeroMemory(&startup, sizeof startup);
    startup.cb = sizeof startup;
    ZeroMemory(&process, sizeof process);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, folder, &startup, &process)) {
        _snwprintf(message, 599, L"The app could not be started (Windows error %lu).\n\n"
                                 L"Extract the whole zip again and keep every file and folder together.",
                   (unsigned long)GetLastError());
        message[599] = L'\0';
        fail(message);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
