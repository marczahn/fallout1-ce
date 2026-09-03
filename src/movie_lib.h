#ifndef MOVIE_LIB_H
#define MOVIE_LIB_H

#include <SDL.h>

namespace fallout {

typedef void*(MveMallocFunc)(size_t size);
typedef void(MveFreeFunc)(void* ptr);
typedef bool MovieReadProc(void* handle, void* buffer, int count);
typedef void(MovieShowFrameProc)(SDL_Surface*, int, int, int, int, int, int, int, int);

void movieLibSetMemoryProcs(MveMallocFunc* mallocProc, MveFreeFunc* freeProc);
void movieLibSetReadProc(MovieReadProc* readProc);
void movieLibSetVolume(int volume);
void movieLibSetPan(int pan);
void _MVE_sfSVGA(int a1, int a2, int a3, int a4, int a5, int a6, int a7, int a8, int a9);
void _MVE_sfCallbacks(MovieShowFrameProc* proc);
void movieLibSetPaletteEntriesProc(void (*fn)(unsigned char*, int, int));
void _MVE_rmCallbacks(int (*fn)());
void _sub_4F4BB(int a1);
void _MVE_rmFrameCounts(int* a1, int* a2);
int _MVE_rmPrepMovie(void* handle, int a2, int a3, char a4);
int _MVE_rmStepMovie();
void _MVE_rmEndMovie();
void _MVE_ReleaseMem();

// Fallout's Interplay-DPCM delta table: 256 entries, indexed by one input
// byte, added to a running `unsigned short` predictor. Read-only, and NOT the
// standard Interplay table - index 112 is 17685, max positive delta 32589.
//
// Exposed so the companion server's standalone MVE audio reader decodes with
// the SAME table the engine plays with, rather than a transcribed copy. A copy
// of 256 hex values is exactly the kind of silent divergence that the
// companion transmission work has already been bitten by once (TASK-023's
// Python decoder). This is a pure getter over a file-static array; it touches
// nothing in the playback path.
const unsigned short* companionMveDeltaTable();

} // namespace fallout

#endif /* MOVIE_LIB_H */
