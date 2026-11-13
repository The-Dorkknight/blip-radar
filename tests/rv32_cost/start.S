  .section .text.start
  .globl _start
_start:
  li sp, 0x80380000
  call main
  .globl done_marker
done_marker:
  j done_marker
