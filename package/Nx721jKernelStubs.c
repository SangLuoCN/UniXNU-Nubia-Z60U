// NX721J keeps the optional LegacyDisplay implementation disabled. The
// generic offline graphics probe still references this hook, so provide only
// the symbol required by the kernel link; no display code is enabled here.
void native_legacy_display_probe(void) {}
