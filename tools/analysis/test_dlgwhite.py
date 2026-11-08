"""Exercise the actual fill helper, including non-recording and reject paths."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import utwindow_compile
import vine_extract
ROOT = Path(__file__).resolve().parents[2]

class DlgwhiteTests(unittest.TestCase):
    def test_actual_helper(self):
        gcc = shutil.which('gcc') or next((str(p) for p in (
            Path('C:/devkitPro/msys2/ucrt64/bin/gcc.exe'),
            Path('C:/devkitPro/msys2/mingw64/bin/gcc.exe')) if p.is_file()), None)
        if not gcc: self.skipTest('host gcc unavailable')
        helper = (ROOT/'platform/3ds/source/ctr_dlgwhite.inc').read_text()
        helper = re.sub(r'__attribute__\(\(.*\)\)\n', '', helper)
        helper = helper.replace('bool originalSolid(const CtrRenderer*, const CtrColor*) __asm__("solidDrawIsNoop");', '')
        driver = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#define ENABLE_WAD16 1
#define nullptr NULL
typedef struct {bool noop, recording; int original, queries;} CtrRenderer;
typedef int CtrColor;
static bool originalSolid(const CtrRenderer* r, const CtrColor* c) {
    (void)c; ((CtrRenderer*)r)->original++; return r->noop;
}
static void* recordingSurface(CtrRenderer* r) {r->queries++; return r->recording ? r : NULL;}
// HELPER
int main(void) {
    for (int noop=0;noop<2;noop++) for (int rec=0;rec<2;rec++) {
        CtrRenderer r={noop,rec,0,0}; CtrColor c=0;
        assert(CtrDlgwhite_solidDrawIsNoop(&r,&c)==(noop && !rec));
        assert(r.original==1 && r.queries==noop);
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='dlgwhite-') as temp:
            c=Path(temp)/'test.c';exe=Path(temp)/'test.exe';c.write_text(driver.replace('// HELPER', helper))
            subprocess.run([gcc,'-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],
                           stdin=subprocess.DEVNULL,timeout=30,check=True)
            subprocess.run([str(exe)],stdin=subprocess.DEVNULL,timeout=10,check=True)

    def test_scoped_call_and_fail_closed(self):
        original=('other:\n\tbl solidDrawIsNoop\n\t.size other, .-other\n'
                  'emitQuad:\n\tbl solidDrawIsNoop\n\t.size emitQuad, .-emitQuad\n')
        result=utwindow_compile.route_solid(original)
        self.assertEqual(result.replace('CtrDlgwhite_solidDrawIsNoop','solidDrawIsNoop'),original)
        self.assertEqual(result.count('CtrDlgwhite_solidDrawIsNoop'),1)
        for bad in (original+original, original.replace('\tbl solidDrawIsNoop','\tb solidDrawIsNoop'),result):
            with self.assertRaises(AssertionError):utwindow_compile.route_solid(bad)

    def test_no_original_sections_from_helper_pass(self):
        text='\t.text\noriginal:\n\tbx lr\n\t.section .text_dlgwhite,"ax",%progbits\nhelper:\n\tbx lr\n\t.section .rodata\ndata:\n\t.word 1\n'
        result, sections=vine_extract.late_sections(text,'dlgwhite')
        self.assertEqual(sections,['.text_dlgwhite'])
        self.assertIn('helper:',result)
        self.assertNotIn('original:',result)
        self.assertNotIn('data:',result)

if __name__=='__main__':unittest.main()
