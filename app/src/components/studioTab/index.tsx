import React, { useState, useEffect } from 'react';
import { Video, Download, FileText, RotateCcw, Settings2, Sliders, Cpu } from 'lucide-react'; // Thêm icon Cpu cho trực quan
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/use-toast';
import { motion, AnimatePresence } from 'framer-motion';
import { usePlayerStore } from '@/stores/playerStore';
import { useUIStore } from '@/stores/uiStore'; 
import { FloatingGenerateBox } from '@/components/Generation/FloatingGenerateBox';

export default function StudioTab() {
  const { toast } = useToast();
  const API_BASE = 'http://127.0.0.1:17493';
  
  const audioUrl = usePlayerStore((state) => state.audioUrl);
  const selectedProfileId = useUIStore((state) => state.selectedProfileId);
  const selectedEngine = useUIStore((state) => state.selectedEngine);
  const selectedLanguage = useUIStore((state) => (state as any).selectedLanguage || 'vi');
  
  const [url, setUrl] = useState('');
  const [cookie, setCookie] = useState('');
  const [mixer, setMixer] = useState({ bg: 50, vocal: 10, dub: 200 });
  const [settings, setSettings] = useState({ createSub: true, burnSub: false });
  
  // 1. CHỈNH SỬA: Thêm state quản lý số luồng (Mặc định là 3 luồng)
  const [numThreads, setNumThreads] = useState(5);

  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('');
  const [result, setResult] = useState<{ videoId?: string; videoUrl?: string; subUrl?: string } | null>(null);

  // --- TỰ ĐỘNG CHECK KHI DÁN LINK ---
  useEffect(() => {
    const check = async () => {
      if (url.length > 20 && (url.includes('v=') || url.includes('youtu.be'))) {
        try {
          const r = await fetch(`${API_BASE}/check-exists?url=${encodeURIComponent(url)}`);
          const d = await r.json();
          if (d.exists) {
            setResult({ videoId: d.video_id, videoUrl: d.video_url, subUrl: d.sub_url });
            toast({ title: "Hàng sẵn có!", description: "Video này đã được lồng tiếng." });
          }
        } catch (e) { console.error(e); }
      }
    };
    const t = setTimeout(check, 800);
    return () => clearTimeout(t);
  }, [url]);

  // --- HÀM TẢI FILE (GỌI THẲNG API DOWNLOAD) ---
  const handleDownload = (vid: string, type: 'mp4' | 'srt') => {
    window.location.href = `${API_BASE}/download-file/${vid}?type=${type}`;
  };

  const handleRun = async () => {
    if (!url || !selectedProfileId) return;
    setIsProcessing(true);
    setProgress(0);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url, cookie, profile_id: selectedProfileId, model_id: selectedEngine,
          target_lang: selectedLanguage, bg_vol: mixer.bg, vocal_vol: mixer.vocal,
          dub_vol: mixer.dub, create_sub: settings.createSub, burn_sub: settings.burnSub,
          
          // 2. CHỈNH SỬA: Gửi kèm số luồng (num_threads) lên Backend API
          num_threads: numThreads 
        })
      });
      const data = await resp.json();
      if (resp.ok) trackProgress(data.task_id);
    } catch (e) { setIsProcessing(false); }
  };

  const trackProgress = (tid: string) => {
    const itv = setInterval(async () => {
      const r = await fetch(`${API_BASE}/progress/${tid}`);
      const s = await r.json();
      setProgress(s.percent);
      setStatus(s.status);
      if (s.percent === 100) {
        clearInterval(itv);
        setIsProcessing(false);
        setResult({ videoId: s.video_id, videoUrl: s.video_url, subUrl: s.sub_url });
      } else if (s.percent === -1) {
        clearInterval(itv);
        setIsProcessing(false);
      }
    }, 1000);
  };

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden relative">
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full pb-32">
        <div className="flex items-center gap-2 border-b border-accent/20 pb-4 mb-6">
          <Video className="text-accent h-6 w-6" />
          <h1 className="text-2xl font-bold">AI Dubbing Studio</h1>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-6">
            <div className="bg-card/50 backdrop-blur-md border border-accent/10 rounded-[2rem] p-6 shadow-xl space-y-4">
              <h2 className="text-sm font-semibold flex items-center gap-2 text-primary"><Settings2 className="w-4 h-4" /> Cấu hình</h2>
              <Input placeholder="Dán link YouTube..." value={url} onChange={(e) => setUrl(e.target.value)} className="rounded-2xl" />
              <textarea placeholder="Cookie..." className="w-full h-24 p-4 rounded-2xl bg-background/50 border border-accent/20 text-sm outline-none" value={cookie} onChange={(e) => setCookie(e.target.value)} />
              
              <div className="grid grid-cols-2 gap-4">
                <div className="flex items-center justify-between p-3 border border-accent/20 rounded-xl">
                  <span className="text-xs">Tạo Sub</span>
                  <Switch checked={settings.createSub} onCheckedChange={v => setSettings({...settings, createSub: v})} />
                </div>
                <div className="flex items-center justify-between p-3 border border-orange-500/50 rounded-xl">
                  <span className="text-xs">Burn Sub</span>
                  <Switch checked={settings.burnSub} onCheckedChange={v => setSettings({...settings, burnSub: v})} />
                </div>
              </div>

              {/* 3. CHỈNH SỬA: Thêm thanh trượt tùy chỉnh số luồng chạy song song */}
              <div className="space-y-2 p-4 border border-accent/20 rounded-xl bg-accent/5">
                <div className="flex justify-between items-center text-xs">
                  <span className="flex items-center gap-1.5 font-medium">
                    <Cpu className="w-3.5 h-3.5 text-accent" /> Số luồng xử lý đồng thời
                  </span>
                  <span className="font-bold text-accent bg-accent/10 px-2 py-0.5 rounded-md">{numThreads} luồng</span>
                </div>
                <Slider 
                  value={[numThreads]} 
                  onValueChange={v => setNumThreads(v[0])} 
                  min={1} 
                  max={10} 
                  step={1} 
                  className="py-2"
                />
                <p className="text-[10px] text-muted-foreground italic">
                  * Khuyến nghị: 3 - 5 luồng tùy vào sức mạnh card đồ họa của bạn.
                </p>
              </div>

              <Button className="w-full h-14 rounded-2xl font-bold" onClick={handleRun} disabled={isProcessing}>
                {isProcessing ? 'Đang Render...' : '🚀 Bắt đầu Render'}
              </Button>
              <AnimatePresence>
                {isProcessing && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2 p-4 border border-accent/20 rounded-xl bg-accent/5">
                    <div className="flex justify-between text-sm"><span>{status}</span><span className="font-bold">{progress}%</span></div>
                    <Progress value={progress} className="h-2" />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          <div className="space-y-6">
            <div className="bg-card/50 backdrop-blur-md border border-accent/10 rounded-[2rem] p-6 shadow-xl space-y-6">
              <h3 className="text-sm font-semibold flex items-center gap-2"><Sliders className="w-4 h-4" /> Mixer</h3>
              <div className="space-y-4">
                <div className="space-y-2"><div className="flex justify-between text-xs"><span>Nhạc nền</span><span>{mixer.bg}%</span></div><Slider value={[mixer.bg]} onValueChange={v => setMixer({...mixer, bg: v[0]})} max={100} /></div>
                <div className="space-y-2"><div className="flex justify-between text-xs"><span>Giọng gốc</span><span>{mixer.vocal}%</span></div><Slider value={[mixer.vocal]} onValueChange={v => setMixer({...mixer, vocal: v[0]})} max={100} /></div>
                <div className="space-y-2"><div className="flex justify-between text-xs"><span>Lồng tiếng</span><span>{mixer.dub}%</span></div><Slider value={[mixer.dub]} onValueChange={v => setMixer({...mixer, dub: v[0]})} max={200} /></div>
              </div>
            </div>

            <AnimatePresence>
              {result && (
                <motion.div initial={{ scale: 0.9 }} animate={{ scale: 1 }} className="space-y-4 p-6 border border-accent/20 rounded-[2rem] bg-card/50 shadow-xl">
                  <video key={result.videoUrl} src={result.videoUrl} controls className="w-full rounded-xl bg-black" />
                  <div className="flex gap-2">
                    <Button variant="outline" className="flex-1 rounded-xl" onClick={() => handleDownload(result.videoId!, 'mp4')}><Download className="h-4 w-4 mr-2" /> Tải Video</Button>
                    {result.subUrl && <Button variant="outline" className="flex-1 rounded-xl" onClick={() => handleDownload(result.videoId!, 'srt')}><FileText className="h-4 w-4 mr-2" /> Tải Sub</Button>}
                    <Button variant="ghost" onClick={() => {setResult(null); setUrl('');}}><RotateCcw className="h-4 w-4" /></Button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    {/* 1. Tìm chỗ gọi FloatingGenerateBox cũ và thay bằng cụm này */}
<div id="force-center-box">
  <FloatingGenerateBox showVoiceSelector isPlayerOpen={!!audioUrl} />
</div>

{/* 2. Thêm đoạn mã CSS này vào ngay phía trên lệnh return (hoặc bất kỳ đâu trong file) */}
<style>{`
  #force-center-box > div {
    left: 50% !important;
    transform: translateX(-50%) !important;
    width: 100% !important;
    max-width: 1024px !important; /* khớp với max-w-5xl (1024px) */
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
  }
`}</style>
    </div>
  );
}