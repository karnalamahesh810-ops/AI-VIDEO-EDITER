import subprocess, sys, numpy as np
v = sys.argv[1]
for t in map(float, sys.argv[2:]):
    p = subprocess.run(["ffmpeg","-v","error","-ss",f"{t-0.4:.3f}","-t","1.2","-i",v,"-ac","1","-ar","32000","-af","highpass=f=4000","-f","s16le","-"],capture_output=True)
    a = np.frombuffer(p.stdout,np.int16).astype(float)
    p2 = subprocess.run(["ffmpeg","-v","error","-ss",f"{t-0.4:.3f}","-t","1.2","-i",v,"-ac","1","-ar","32000","-f","s16le","-"],capture_output=True)
    b = np.frombuffer(p2.stdout,np.int16).astype(float)
    n=640
    hb=[10*np.log10((a[i:i+n]**2).mean()/32768**2+1e-12) for i in range(0,len(a)-n,n)]
    fb=[10*np.log10((b[i:i+n]**2).mean()/32768**2+1e-12) for i in range(0,len(b)-n,n)]
    print(f"{t:7.2f} HB " + " ".join(f"{x:4.0f}" for x in hb[::2]))
    print(f"        FB " + " ".join(f"{x:4.0f}" for x in fb[::2]))
