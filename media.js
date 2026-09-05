// media.js - 本地媒体库（音乐播放器 / 视频播放器 / 扫描目录弹窗）
// 从 index.html 拆出，在主脚本之前通过 <script src> 引入

        // ============ 本地音乐播放器 ============
        let musicData = { categories: [{id:'default',name:'未分类'}], files: [], scanRoots: [], activeCat: '__all__', search: '' };
        let musicAudio = null;
        let musicCurrentId = null;
        let musicQueue = [];
        let musicServerOk = false;
        let musicTabActive = false;
        let musicPlayMode = localStorage.getItem('musicPlayMode') || 'loop'; // loop | one | shuffle
        let musicCoverObserver = null;
        let musicCoverInProgress = new Set();
        let musicTagsFailed = new Set();
        let musicLrc = [];
        let musicLrcIdx = -1;

        // ---- 共用：拖拽进度条/音量条 helper（音乐 + 视频共用） ----
        // opts.live: true=拖动实时生效（音量条）；false/缺省=拖动中只更新进度 UI，松手才生效
        // （进度条若拖动中实时 seek，每次赋值都会取消并重发媒体 Range 请求，造成请求风暴+卡顿）
        function mediaBindTrack(trackEl, fillEl, onFraction, tipEl, getTipText, opts) {
            if (!trackEl) return;
            const live = !!(opts && opts.live);
            let dragging = false, pendingF = null;
            const calc = (e) => {
                const rect = trackEl.getBoundingClientRect();
                if (rect.width <= 0) return 0;
                return Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
            };
            const apply = (f) => {
                fillEl && (fillEl.style.width = (f * 100) + '%');
                if (live) onFraction(f); else pendingF = f;
            };
            trackEl.addEventListener('pointerdown', (e) => {
                dragging = true;
                trackEl.classList.add('dragging');
                try { trackEl.setPointerCapture(e.pointerId); } catch(_){}
                apply(calc(e));
            });
            trackEl.addEventListener('pointermove', (e) => {
                const f = calc(e);
                if (tipEl) {
                    tipEl.style.display = 'block';
                    tipEl.style.left = (f * trackEl.getBoundingClientRect().width) + 'px';
                    if (getTipText) tipEl.textContent = getTipText(f);
                }
                if (dragging) apply(f);
            });
            const stopDrag = (e) => {
                if (!dragging) return;
                dragging = false;
                trackEl.classList.remove('dragging');
                try { trackEl.releasePointerCapture(e.pointerId); } catch(_){}
                if (!live && pendingF !== null) { const f = pendingF; pendingF = null; onFraction(f); }
            };
            trackEl.addEventListener('pointerup', stopDrag);
            trackEl.addEventListener('pointercancel', stopDrag);
            trackEl.addEventListener('pointerleave', () => { if (tipEl) tipEl.style.display = 'none'; });
        }

        function musicInit() {
            musicAudio = document.getElementById('musicAudio');
            musicAudio.addEventListener('timeupdate', () => {
                musicUpdateProgressUI();
                musicLrcTick();
            });
            musicAudio.addEventListener('loadedmetadata', () => {
                const dur = musicAudio.duration;
                musicUpdateProgressUI();
                if (musicCurrentId && dur && isFinite(dur)) {
                    const f = musicData.files.find(x => x.id === musicCurrentId);
                    if (f && !f.duration) {
                        f.duration = dur;
                        fetch('/api/media/file-meta', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: musicCurrentId, duration: dur})});
                    }
                }
            });
            musicAudio.addEventListener('ended', () => musicNext());
            musicAudio.addEventListener('error', () => showToast('文件无法播放：可能已移动或格式不支持', 'error'));
            musicAudio.addEventListener('play', () => musicUpdatePlayIcons());
            musicAudio.addEventListener('pause', () => musicUpdatePlayIcons());
            // 进度条（底栏 + 详情面板）
            mediaBindTrack(document.getElementById('musicTrack'), document.getElementById('musicFill'), f => { if (musicAudio.duration && isFinite(musicAudio.duration)) musicAudio.currentTime = f * musicAudio.duration; });
            mediaBindTrack(document.getElementById('musicNowTrack'), document.getElementById('musicNowFill'), f => { if (musicAudio.duration && isFinite(musicAudio.duration)) musicAudio.currentTime = f * musicAudio.duration; });
            // 音量
            const savedVol = parseFloat(localStorage.getItem('musicVol'));
            musicSetVolume(isNaN(savedVol) ? 1 : savedVol);
            mediaBindTrack(document.getElementById('musicVolSlider'), document.getElementById('musicVolFill'), f => musicSetVolume(f));
            // 移动端长按歌曲行呼出分类菜单
            mediaBindLongPress(document.getElementById('musicBody'), 'tr[data-mid]', (x, y, el) => musicShowCatMenu({ clientX: x, clientY: y }, el.dataset.mid));
            // 歌词点击跳转（事件委托）
            document.getElementById('musicNowLyrics').addEventListener('click', (e) => {
                const line = e.target.closest('.music-lrc-line');
                if (line && line.dataset.t) musicAudio.currentTime = parseFloat(line.dataset.t);
            });
            musicApplyModeUI();
            // 封面懒提取 observer
            musicInitCoverObserver();
            // 播放列表面板点外部关闭
            document.addEventListener('click', (e) => {
                const panel = document.getElementById('musicPlaylistPanel');
                if (panel.style.display === 'none') return;
                if (!panel.contains(e.target) && !e.target.closest('#musicPlayer') && !e.target.closest('.music-now-ctrl')) panel.style.display = 'none';
            });
            // 探测服务器
            fetch('/api/media').then(r => r.json()).then(j => {
                if (j.success) {
                    musicServerOk = true;
                    document.getElementById('musicTabBtn').style.display = '';
                    musicLoadFromServer(j.data);
                    musicRender();
                }
            }).catch(() => {});
        }

        function musicTabOn() { musicTabActive = true; }
        function musicTabOff() { musicTabActive = false; }

        function musicLoadFromServer(lib) {
            const cats = (lib.categories && lib.categories.music) || [{id:'default',name:'未分类'}];
            const files = (lib.files || []).filter(f => f.type === 'music');
            musicData.categories = cats;
            musicData.files = files;
            musicData.scanRoots = ((lib.scanRoots && lib.scanRoots.music) || []).map(mediaNormRoot);
        }

        function musicSyncToServer() {
            const payload = {
                categories: { music: musicData.categories },
                files: musicData.files.map(f => ({ id: f.id, categoryId: f.categoryId, customName: f.customName || '', duration: f.duration, thumbFile: f.thumbFile }))
            };
            fetch('/api/media', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        }

        // ===== 通用右键菜单（视频/音乐共用） =====
        let mediaCtxMenuEl = null;
        function mediaCloseCtxMenu() { if (mediaCtxMenuEl) { mediaCtxMenuEl.remove(); mediaCtxMenuEl = null; } }
        function mediaShowMenu(x, y, items) {
            mediaCloseCtxMenu();
            const el = document.createElement('div');
            el.className = 'media-ctx-menu';
            const render = (list) => list.map(it => {
                if (it.type === 'sep') return '<div class="mcm-sep"></div>';
                if (it.type === 'sub') return `<div class="mcm-item has-sub"><span>${it.label}</span><span class="mcm-arrow">▸</span><div class="mcm-sub">${render(it.items)}</div></div>`;
                return `<div class="mcm-item ${it.active ? 'active' : ''}" data-act="${it.act}" data-id="${it.id || ''}">${it.label}</div>`;
            }).join('');
            el.innerHTML = render(items);
            document.body.appendChild(el);
            const r = el.getBoundingClientRect();
            el.style.left = Math.max(8, Math.min(x, window.innerWidth - r.width - 8)) + 'px';
            el.style.top = Math.max(8, Math.min(y, window.innerHeight - r.height - 8)) + 'px';
            // 右侧空间不足时子菜单向左展开
            if (x + r.width + 220 > window.innerWidth) el.classList.add('sub-left');
            mediaCtxMenuEl = el;
            el.addEventListener('contextmenu', e => e.preventDefault());
            el.addEventListener('click', (e) => {
                const t = e.target.closest('.mcm-item');
                if (!t || t.classList.contains('has-sub')) return;
                const act = t.dataset.act, id = t.dataset.id;
                mediaCloseCtxMenu();
                if (act === 'video-play') return videoPlay(id);
                if (act === 'video-thumb') return videoRegenThumb(id);
                if (act === 'video-setcat') return videoSetCategory(id);
                if (act === 'video-newcat') return videoNewCatAndAssign(id);
                if (act === 'music-setcat') return musicSetCategory(id);
                if (act === 'music-newcat') return musicNewCatAndAssign(id);
            });
        }
        document.addEventListener('click', () => mediaCloseCtxMenu());
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') mediaCloseCtxMenu(); });

        // ---- 移动端长按呼出右键菜单（与 PC 端 oncontextmenu 等价） ----
        // container: 委托容器；targetSelector: 可长按元素；onLongPress(x, y, el)
        function mediaBindLongPress(container, targetSelector, onLongPress) {
            if (!container || container._lpBound) return;
            container._lpBound = true;
            let timer = null, fired = false, sx = 0, sy = 0;
            container.addEventListener('touchstart', (e) => {
                const el = e.target.closest(targetSelector);
                if (!el) return;
                fired = false;
                const t = e.touches[0];
                sx = t.clientX; sy = t.clientY;
                timer = setTimeout(() => {
                    fired = true;
                    mediaCloseCtxMenu();
                    onLongPress(sx, sy, el);
                    if (navigator.vibrate) navigator.vibrate(20);
                }, 500);
            }, { passive: true });
            // 手指移动超过阈值视为滚动，取消长按
            container.addEventListener('touchmove', (e) => {
                if (!timer) return;
                const t = e.touches[0];
                if (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10) { clearTimeout(timer); timer = null; }
            }, { passive: true });
            container.addEventListener('touchend', (e) => {
                clearTimeout(timer); timer = null;
                if (fired) e.preventDefault(); // 阻止长按后合成 click（避免误触播放）
            });
            container.addEventListener('touchcancel', () => { clearTimeout(timer); timer = null; });
        }

        function musicRender() {
            const search = (document.getElementById('musicSearch')?.value || '').toLowerCase();
            const cat = musicData.activeCat;
            let list = musicData.files;
            if (cat !== '__all__') list = list.filter(f => (f.categoryId || 'default') === cat);
            if (search) list = list.filter(f => f.name.toLowerCase().includes(search) || (f.dir||'').toLowerCase().includes(search));
            musicQueue = list;

            // 分类侧栏
            const catList = document.getElementById('musicCatList');
            const allCount = musicData.files.length;
            let html = `<div class="media-cat-item ${cat==='__all__'?'active':''}" onclick="musicSelectCategory('__all__')"><span>全部</span><span class="media-cat-count">${allCount}</span></div>`;
            for (const c of musicData.categories) {
                const cnt = musicData.files.filter(f => (f.categoryId||'default') === c.id).length;
                const bound = musicData.scanRoots.filter(r => r.categoryId === c.id);
                const bindBadge = bound.length ? `<span class="media-cat-bind" title="绑定扫描目录：&#10;${escapeHtml(bound.map(r => r.path).join('\n'))}">📁${bound.length}</span>` : '';
                const canDel = c.id !== 'default';
                html += `<div class="media-cat-item ${cat===c.id?'active':''}" onclick="musicSelectCategory('${c.id}')" oncontextmenu="event.preventDefault();musicRenameCategory('${c.id}')"><span>${escapeHtml(c.name)}</span>${bindBadge}<span class="media-cat-count">${cnt}</span><span class="media-cat-acts">${canDel?`<span class="media-cat-del" title="删除分类" onclick="event.stopPropagation();musicDeleteCategory('${c.id}')">×</span>`:''}<span class="media-cat-edit" title="重命名分类" onclick="event.stopPropagation();musicRenameCategory('${c.id}')">✏</span></span></div>`;
            }
            catList.innerHTML = html;

            // 歌曲列表
            const body = document.getElementById('musicBody');
            if (list.length === 0) {
                body.innerHTML = '';
                document.getElementById('musicEmpty').style.display = 'flex';
            } else {
                document.getElementById('musicEmpty').style.display = 'none';
                body.innerHTML = list.map((f, i) => {
                    const catName = (musicData.categories.find(c => c.id === (f.categoryId||'default'))||{}).name || '未分类';
                    const artist = (f.tags && f.tags.artist) || '';
                    const coverCell = f.coverFile
                        ? `<div class="music-row-cover"><img src="/media_cover?id=${f.id}" alt=""></div>`
                        : `<div class="music-row-cover" data-id="${f.id}"><span>🎵</span></div>`;
                    return `<tr data-mid="${f.id}" class="${f.id===musicCurrentId?'playing':''}" onclick="musicPlay('${f.id}')" oncontextmenu="event.preventDefault();musicShowCatMenu(event,'${f.id}')">
                        <td>${i+1}</td>
                        <td style="width:44px;">${coverCell}</td>
                        <td class="music-cell-title">${f.customName || (f.tags && f.tags.title) || f.name}${artist?`<div class="music-cell-sub">${artist}</div>`:''}</td>
                        <td style="color:#9ca3af;font-size:12px;">${(f.dir||'').split(/[\\/]/).pop()||'-'}</td>
                        <td><span class="music-row-cat" onclick="event.stopPropagation();musicShowCatMenu(event,'${f.id}')">${catName}</span></td>
                        <td style="color:#9ca3af;">${f.duration?musicFmtTime(f.duration):'-'}</td>
                    </tr>`;
                }).join('');
            }
            document.getElementById('musicCount').textContent = `共 ${list.length} 首`;
            // 观察无封面行，懒提取
            if (musicCoverObserver) {
                body.querySelectorAll('.music-row-cover[data-id]').forEach(el => musicCoverObserver.observe(el));
            }
            if (document.getElementById('musicPlaylistPanel').style.display !== 'none') musicRenderPlaylist();
        }

        function musicSelectCategory(id) { musicData.activeCat = id; musicRender(); }

        function musicAddCategory() {
            const name = prompt('输入分类名称：');
            if (!name || !name.trim()) return;
            const id = 'c_' + Date.now().toString(36);
            musicData.categories.push({ id, name: name.trim() });
            musicSyncToServer(); musicRender();
        }
        function musicRenameCategory(id) {
            const c = musicData.categories.find(x => x.id === id);
            if (!c) return;
            const name = prompt('重命名分类：', c.name);
            if (!name || !name.trim()) return;
            c.name = name.trim();
            musicSyncToServer(); musicRender();
        }
        function musicDeleteCategory(id) {
            if (!confirm('确认删除该分类？分类内文件将归入"未分类"')) return;
            musicData.categories = musicData.categories.filter(c => c.id !== id);
            musicData.files.forEach(f => { if (f.categoryId === id) f.categoryId = 'default'; });
            musicData.scanRoots.forEach(r => { if (r.categoryId === id) r.categoryId = 'default'; });
            if (musicData.activeCat === id) musicData.activeCat = '__all__';
            musicSyncToServer(); musicRender();
        }
        function musicShowCatMenu(e, fileId) {
            const f = musicData.files.find(x => x.id === fileId);
            if (!f) return;
            const cur = f.categoryId || 'default';
            mediaShowMenu(e.clientX, e.clientY, [
                { label: '移动到分类', type: 'sub', items: [
                    ...musicData.categories.map(c => ({ label: (c.id === cur ? '✓ ' : '') + escapeHtml(c.name), act: 'music-setcat', id: fileId + '|' + c.id, active: c.id === cur })),
                    { label: '＋ 新建分类…', act: 'music-newcat', id: fileId }
                ] }
            ]);
        }
        function musicSetCategory(payload) {
            const i = payload.lastIndexOf('|');
            const f = musicData.files.find(x => x.id === payload.slice(0, i));
            if (!f) return;
            f.categoryId = payload.slice(i + 1);
            musicSyncToServer(); musicRender();
            const c = musicData.categories.find(x => x.id === f.categoryId);
            showToast('已移动到分类：' + (c ? c.name : '未分类'), 'success', 1500);
        }
        function musicNewCatAndAssign(fileId) {
            const name = prompt('输入新分类名称：');
            if (!name || !name.trim()) return;
            const cid = 'c_' + Date.now().toString(36);
            musicData.categories.push({ id: cid, name: name.trim() });
            const f = musicData.files.find(x => x.id === fileId);
            if (f) f.categoryId = cid;
            musicSyncToServer(); musicRender();
            showToast('已创建分类「' + name.trim() + '」并移入', 'success', 1500);
        }

        function musicPlay(id) {
            const f = musicData.files.find(x => x.id === id);
            if (!f) return;
            musicCurrentId = id;
            musicAudio.src = '/media_file?id=' + id;
            musicAudio.play().catch(() => {});
            document.getElementById('musicTitle').textContent = f.customName || (f.tags && f.tags.title) || f.name;
            document.getElementById('musicArtist').textContent = (f.tags && f.tags.artist) || (f.dir||'').split(/[\\/]/).pop() || '';
            musicPaintCovers(f);
            musicEnsureTags(f);
            if (document.getElementById('musicNowModal').style.display !== 'none') musicLoadLrc(f);
            musicRender();
        }
        function musicToggle() {
            if (!musicCurrentId) { if (musicQueue.length) musicPlay(musicQueue[0].id); return; }
            if (musicAudio.paused) musicAudio.play(); else musicAudio.pause();
        }
        function musicUpdatePlayIcons() {
            const icon = musicAudio.paused ? '▶' : '⏸';
            const btn1 = document.getElementById('musicPlayBtn');
            const btn2 = document.getElementById('musicNowPlayBtn');
            if (btn1) btn1.textContent = icon;
            if (btn2) btn2.textContent = icon;
        }
        function musicPickIndex(dir) {
            if (!musicQueue.length) return -1;
            const idx = musicQueue.findIndex(f => f.id === musicCurrentId);
            if (musicPlayMode === 'shuffle') {
                if (musicQueue.length === 1) return 0;
                let r;
                do { r = Math.floor(Math.random() * musicQueue.length); } while (r === idx);
                return r;
            }
            if (idx === -1) return 0;
            return (idx + dir + musicQueue.length) % musicQueue.length;
        }
        function musicPrev() {
            const i = musicPickIndex(-1);
            if (i >= 0) musicPlay(musicQueue[i].id);
        }
        function musicNext() {
            const i = musicPickIndex(1);
            if (i >= 0) musicPlay(musicQueue[i].id);
        }
        function musicFmtTime(sec) {
            if (!sec || !isFinite(sec)) return '0:00';
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60);
            return m + ':' + (s < 10 ? '0' : '') + s;
        }

        // ---- 播放模式 ----
        function musicCycleMode() {
            musicPlayMode = musicPlayMode === 'loop' ? 'one' : musicPlayMode === 'one' ? 'shuffle' : 'loop';
            localStorage.setItem('musicPlayMode', musicPlayMode);
            musicApplyModeUI();
            showToast(musicPlayMode === 'loop' ? '列表循环' : musicPlayMode === 'one' ? '单曲循环' : '随机播放', 'info');
        }
        function musicApplyModeUI() {
            const icon = musicPlayMode === 'loop' ? '🔁' : musicPlayMode === 'one' ? '🔂' : '🔀';
            const title = musicPlayMode === 'loop' ? '列表循环' : musicPlayMode === 'one' ? '单曲循环' : '随机播放';
            const b1 = document.getElementById('musicModeBtn');
            const b2 = document.getElementById('musicNowModeBtn');
            if (b1) { b1.textContent = icon; b1.title = title; }
            if (b2) { b2.textContent = icon; b2.title = title; }
            if (musicAudio) musicAudio.loop = (musicPlayMode === 'one');
        }

        // ---- 进度 UI ----
        function musicUpdateProgressUI() {
            const cur = musicAudio.currentTime || 0;
            const dur = musicAudio.duration || 0;
            const frac = (dur > 0 && isFinite(dur)) ? Math.min(1, cur / dur) : 0;
            const f1 = document.getElementById('musicFill');
            const f2 = document.getElementById('musicNowFill');
            if (f1) f1.style.width = (frac * 100) + '%';
            if (f2) f2.style.width = (frac * 100) + '%';
            const curT = musicFmtTime(cur), totT = musicFmtTime(dur);
            const setC = (id) => { const el = document.getElementById(id); if (el) el.textContent = curT; };
            const setT = (id) => { const el = document.getElementById(id); if (el) el.textContent = totT; };
            setC('musicTimeCur'); setC('musicNowTimeCur');
            setT('musicTimeTotal'); setT('musicNowTimeTotal');
        }

        // ---- 音量 ----
        function musicSetVolume(v) {
            v = Math.min(1, Math.max(0, v));
            musicAudio.volume = v;
            if (v > 0) musicAudio.muted = false;
            localStorage.setItem('musicVol', String(v));
            const fill = document.getElementById('musicVolFill');
            if (fill) fill.style.width = (v * 100) + '%';
            musicUpdateVolIcon();
        }
        function musicMuteToggle() {
            musicAudio.muted = !musicAudio.muted;
            musicUpdateVolIcon();
        }
        function musicUpdateVolIcon() {
            const el = document.getElementById('musicVolIcon');
            if (!el) return;
            const v = musicAudio.muted ? 0 : (musicAudio.volume || 0);
            el.textContent = v === 0 ? '🔇' : v < 0.5 ? '🔉' : '🔊';
        }

        function musicOpenScan() { mediaScanOpen('music'); }
        function musicRescan() {
            if (!musicData.scanRoots.length) { mediaScanOpen('music'); return; }
            musicDoScan(musicData.scanRoots, true);
        }
        function musicDoScan(roots, isRescan) {
            showToast('正在扫描…', 'info');
            fetch('/api/media/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({roots, type:'music'}) })
                .then(r => r.json()).then(j => {
                    if (j.success) {
                        musicLoadFromServer(j.data);
                        musicRender();
                        showToast(`扫描完成，共 ${j.scanned} 首`, 'success');
                    } else { showToast('扫描失败：' + (j.error||''), 'error'); }
                }).catch(() => showToast('扫描请求失败', 'error'));
        }

        // ---- 共用：扫描目录管理弹窗（音乐 / 视频通用） ----
        let mediaScanTarget = null; // 'music' | 'video'
        let mediaScanPendingRemove = new Set();

        function mediaScanData() { return mediaScanTarget === 'music' ? musicData : videoData; }

        // 归一化扫描根条目：兼容旧字符串格式 → {path, categoryId}（目录绑定分类）
        function mediaNormRoot(r) {
            return (r && typeof r === 'object')
                ? { path: String(r.path || ''), categoryId: String(r.categoryId || 'default') }
                : { path: String(r || ''), categoryId: 'default' };
        }
        function mediaScanKey(p) { return String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase(); }
        function mediaSyncCategories() {
            if (mediaScanTarget === 'music') musicSyncToServer();
            else if (mediaScanTarget === 'video') videoSyncToServer();
        }

        function mediaScanOpen(target) {
            mediaScanTarget = target;
            mediaScanPendingRemove = new Set();
            document.getElementById('mediaScanTitle').textContent = target === 'music' ? '管理音乐扫描目录' : '管理视频扫描目录';
            mediaScanFillAddCat('default');
            mediaScanRender();
            document.getElementById('mediaScanOverlay').style.display = 'flex';
            setTimeout(() => document.getElementById('mediaScanInput').focus(), 50);
        }
        function mediaScanClose() {
            document.getElementById('mediaScanOverlay').style.display = 'none';
            mediaScanTarget = null;
        }
        // 填充"添加目录"行的分类下拉
        function mediaScanFillAddCat(selected) {
            const el = document.getElementById('mediaScanCatSelect');
            if (!el) return;
            const data = mediaScanData();
            el.innerHTML = data.categories.map(c =>
                `<option value="${c.id}" ${c.id === selected ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('')
                + '<option value="__new__">➕ 新建分类…</option>';
        }
        function mediaScanAddCatChange() {
            const sel = document.getElementById('mediaScanCatSelect');
            if (!sel || sel.value !== '__new__') return;
            const name = prompt('输入新分类名称：');
            const data = mediaScanData();
            if (!name || !name.trim()) { sel.value = 'default'; return; }
            const cid = 'c_' + Date.now().toString(36);
            data.categories.push({ id: cid, name: name.trim() });
            mediaSyncCategories();
            mediaScanFillAddCat(cid);
        }
        // 目录条目上的分类绑定下拉
        function mediaScanCatSelect(idx, selected) {
            const data = mediaScanData();
            return `<select class="media-scan-cat" onchange="mediaScanSetCat(${idx}, this.value)">` +
                data.categories.map(c =>
                    `<option value="${c.id}" ${c.id === selected ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('') +
                `<option value="__new__" ${selected === '__new__' ? 'selected' : ''}>➕ 新建分类…</option></select>`;
        }
        function mediaScanSetCat(idx, val) {
            const data = mediaScanData();
            const r = data.scanRoots[idx];
            if (!r) return;
            if (val === '__new__') {
                const name = prompt('输入新分类名称：');
                if (!name || !name.trim()) { mediaScanRender(); return; }
                const cid = 'c_' + Date.now().toString(36);
                data.categories.push({ id: cid, name: name.trim() });
                r.categoryId = cid;
                mediaSyncCategories();
            } else {
                r.categoryId = val;
            }
            mediaScanRender();
        }
        function mediaScanRender() {
            const data = mediaScanData();
            const list = document.getElementById('mediaScanList');
            if (!data.scanRoots.length) {
                list.innerHTML = '<div class="media-scan-empty">暂无目录，在下方输入路径添加（支持粘贴多个，用逗号分隔）</div>';
                return;
            }
            list.innerHTML = data.scanRoots.map((r, i) => {
                const removed = mediaScanPendingRemove.has(mediaScanKey(r.path));
                const cnt = data.files.filter(f => (f.dir || '').toLowerCase().startsWith(mediaScanKey(r.path) + '/')).length;
                return `<div class="media-scan-item ${removed ? 'removed' : ''}">
                    <span class="media-scan-icon">📁</span>
                    <div class="media-scan-info"><div class="media-scan-path" title="${r.path}">${r.path}</div><div class="media-scan-meta">${removed ? '移除后将删除其中 ' + cnt + ' 个文件' : cnt + ' 个文件'}</div></div>
                    ${mediaScanCatSelect(i, r.categoryId)}
                    <button class="media-scan-del ${removed ? 'undo' : ''}" onclick="mediaScanToggleRemove(${i})">${removed ? '撤销' : '移除'}</button>
                </div>`;
            }).join('');
        }
        function mediaScanToggleRemove(idx) {
            const data = mediaScanData();
            const r = data.scanRoots[idx];
            if (!r) return;
            const key = mediaScanKey(r.path);
            if (mediaScanPendingRemove.has(key)) mediaScanPendingRemove.delete(key);
            else mediaScanPendingRemove.add(key);
            mediaScanRender();
        }
        function mediaScanAddRoot() {
            const input = document.getElementById('mediaScanInput');
            const raw = input.value.trim();
            if (!raw) return;
            const catSel = document.getElementById('mediaScanCatSelect');
            const cat = (catSel && catSel.value !== '__new__') ? catSel.value : 'default';
            const data = mediaScanData();
            const existing = new Set(data.scanRoots.map(r => mediaScanKey(r.path)));
            const added = [];
            raw.split(/[,,\n;]+/).map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean).forEach(p => {
                const np = mediaScanKey(p);
                if (!np || existing.has(np)) return;
                existing.add(np);
                added.push({ path: p, categoryId: cat });
            });
            if (!added.length) { showToast('目录已存在', 'info'); return; }
            data.scanRoots.push(...added);
            added.forEach(r => mediaScanPendingRemove.delete(mediaScanKey(r.path)));
            input.value = '';
            mediaScanRender();
        }
        function mediaScanConfirm() {
            const data = mediaScanData();
            const target = mediaScanTarget;
            const roots = data.scanRoots
                .filter(r => !mediaScanPendingRemove.has(mediaScanKey(r.path)))
                .map(r => ({ path: r.path, categoryId: r.categoryId }));
            const removeRoots = [...mediaScanPendingRemove];
            if (!roots.length && !removeRoots.length) { mediaScanClose(); return; }
            mediaScanClose();
            showToast('正在扫描…', 'info');
            fetch('/api/media/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({roots, removeRoots, type: target}) })
                .then(r => r.json()).then(j => {
                    if (j.success) {
                        if (target === 'music') { musicLoadFromServer(j.data); musicRender(); }
                        else { videoLoadFromServer(j.data); videoRender(); }
                        const removedNote = removeRoots.length ? `，移除 ${removeRoots.length} 个目录` : '';
                        const recatNote = j.recategorized ? `，自动归类 ${j.recategorized} 个` : '';
                        showToast(`扫描完成${removedNote}${recatNote}`, 'success');
                    } else { showToast('扫描失败：' + (j.error||''), 'error'); }
                }).catch(() => showToast('扫描请求失败', 'error'));
        }

        // ---- 封面 + 标签提取（内置 ID3v2 / FLAC 解析，无外部依赖） ----
        function musicInitCoverObserver() {
            musicCoverObserver = new IntersectionObserver((entries) => {
                entries.forEach(e => {
                    if (!e.isIntersecting) return;
                    const el = e.target;
                    const id = el.dataset.id;
                    if (!id || el.dataset.tried) return;
                    el.dataset.tried = '1';
                    const f = musicData.files.find(x => x.id === id);
                    if (f) musicEnsureTags(f);
                });
            }, { rootMargin: '200px' });
        }

        async function musicEnsureTags(f) {
            if (f.coverFile || musicTagsFailed.has(f.id) || musicCoverInProgress.has(f.id)) return;
            if (!['.mp3', '.flac'].includes(f.ext)) { musicTagsFailed.add(f.id); return; }
            musicCoverInProgress.add(f.id);
            try {
                const res = await fetch('/media_file?id=' + f.id, { headers: { Range: 'bytes=0-524287' } });
                const buf = new Uint8Array(await res.arrayBuffer());
                const meta = f.ext === '.mp3' ? musicParseId3(buf) : musicParseFlac(buf);
                const tags = {};
                if (meta) {
                    if (meta.title) tags.title = String(meta.title).slice(0, 200);
                    if (meta.artist) tags.artist = String(meta.artist).slice(0, 200);
                    if (meta.album) tags.album = String(meta.album).slice(0, 200);
                }
                if (!meta || !meta.picture) {
                    musicTagsFailed.add(f.id);
                    if (Object.keys(tags).length) musicSaveTags(f, tags, null);
                    return;
                }
                const img = await musicDownscaleBlob(meta.picture);
                if (!img) { musicTagsFailed.add(f.id); return; }
                const fd = new FormData();
                fd.append('id', f.id);
                fd.append('tags', JSON.stringify(tags));
                fd.append('file', img, f.id + '.jpg');
                const j = await fetch('/api/media/cover', { method: 'POST', body: fd }).then(r => r.json());
                if (j.success) {
                    f.coverFile = j.coverFile;
                    f.tags = j.tags || tags;
                    musicCoverPaint(f);
                }
            } catch (e) { /* 静默失败 */ }
            finally { musicCoverInProgress.delete(f.id); }
        }

        function musicSaveTags(f, tags, coverFile) {
            // 只有标签没有封面时，走 file-meta 不合适（不含 tags），这里直接用 cover 接口但跳过 —— 保守做法：仅本地生效
            f.tags = Object.assign({}, f.tags || {}, tags);
        }

        function musicCoverPaint(f) {
            document.querySelectorAll(`.music-row-cover[data-id="${f.id}"]`).forEach(el => {
                el.dataset.tried = '1';
                el.innerHTML = `<img src="/media_cover?id=${f.id}" alt="">`;
            });
            if (f.id === musicCurrentId) musicPaintCovers(f);
            if ((f.tags && f.tags.title) && f.id === musicCurrentId) {
                document.getElementById('musicTitle').textContent = f.customName || f.tags.title || f.name;
                if (f.tags.artist) document.getElementById('musicArtist').textContent = f.tags.artist;
            }
        }

        function musicPaintCovers(f) {
            const url = f.coverFile ? '/media_cover?id=' + f.id : null;
            const paint = (imgId, phSel, wrapEl) => {
                const img = document.getElementById(imgId);
                if (!img) return;
                if (url) { img.src = url; img.style.display = ''; const ph = wrapEl.querySelector(phSel); if (ph) ph.style.display = 'none'; }
                else { img.style.display = 'none'; const ph = wrapEl.querySelector(phSel); if (ph) ph.style.display = ''; }
            };
            paint('musicCoverImg', '.music-cover-ph', document.getElementById('musicCover'));
            paint('musicNowCover', '.music-cover-ph', document.getElementById('musicNowCoverWrap'));
            const bg = document.getElementById('musicNowBg');
            if (bg) bg.style.backgroundImage = url ? `url(${url})` : 'none';
        }

        function musicDownscaleBlob(blob) {
            return new Promise((resolve) => {
                const url = URL.createObjectURL(blob);
                const img = new Image();
                img.onload = () => {
                    try {
                        const scale = Math.min(1, 512 / Math.max(img.width, img.height));
                        const c = document.createElement('canvas');
                        c.width = Math.max(1, Math.round(img.width * scale));
                        c.height = Math.max(1, Math.round(img.height * scale));
                        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
                        c.toBlob(b => { URL.revokeObjectURL(url); resolve(b); }, 'image/jpeg', 0.8);
                    } catch (e) { URL.revokeObjectURL(url); resolve(null); }
                };
                img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
                img.src = url;
            });
        }

        function musicParseId3(u8) {
            try {
                if (u8.length < 10 || u8[0] !== 0x49 || u8[1] !== 0x44 || u8[2] !== 0x33) return null; // 'ID3'
                const ver = u8[3];
                if (ver !== 3 && ver !== 4) return null;
                const flags = u8[5];
                const syncsafe = (a, b, c, d) => ((a & 0x7f) << 21) | ((b & 0x7f) << 14) | ((c & 0x7f) << 7) | (d & 0x7f);
                const u32 = (o) => (u8[o] << 24) | (u8[o+1] << 16) | (u8[o+2] << 8) | u8[o+3];
                let size = syncsafe(u8[6], u8[7], u8[8], u8[9]);
                let off = 10;
                // 取缓冲区与标签大小的较小值
                let end = Math.min(10 + size, u8.length);
                let body = u8;
                if (flags & 0x80) {
                    // v2.3 全局反同步：FF 00 → FF
                    const out = new Uint8Array(end - off);
                    let j = 0;
                    for (let i = off; i < end; i++) {
                        out[j++] = u8[i];
                        if (u8[i] === 0xFF && i + 1 < end && u8[i+1] === 0x00) i++;
                    }
                    body = out; off = 0; end = j;
                }
                if (flags & 0x40) {
                    // 扩展头：v2.4 syncsafe 且含自身长度；v2.3 普通 u32 不含自身
                    if (ver === 4) { const es = syncsafe(body[off], body[off+1], body[off+2], body[off+3]); off += es; }
                    else { const es = (body[off]<<24)|(body[off+1]<<16)|(body[off+2]<<8)|body[off+3]; off += 4 + es; }
                }
                const dec = (bytes, encByte) => {
                    try {
                        if (encByte === 0) { let s = ''; for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192)); return s.replace(/\0+$/g, ''); }
                        if (encByte === 1) {
                            if (bytes[0] === 0xFF && bytes[1] === 0xFE) return new TextDecoder('utf-16le').decode(bytes.subarray(2)).replace(/\0+$/g, '');
                            if (bytes[0] === 0xFE && bytes[1] === 0xFF) { const sw = new Uint8Array(bytes.length - 2); for (let i = 0; i < sw.length; i += 2) { sw[i] = bytes[i+2+1]; sw[i+1] = bytes[i+2]; } return new TextDecoder('utf-16le').decode(sw).replace(/\0+$/g, ''); }
                            return new TextDecoder('utf-16le').decode(bytes).replace(/\0+$/g, '');
                        }
                        if (encByte === 2) {
                            try { return new TextDecoder('utf-16be').decode(bytes).replace(/\0+$/g, ''); }
                            catch (_e) { const sw = new Uint8Array(bytes.length); for (let i = 0; i < sw.length - 1; i += 2) { sw[i] = bytes[i+1]; sw[i+1] = bytes[i]; } return new TextDecoder('utf-16le').decode(sw).replace(/\0+$/g, ''); }
                        }
                        return new TextDecoder('utf-8').decode(bytes).replace(/\0+$/g, '');
                    } catch (_e) { return ''; }
                };
                const out = {};
                let bestPic = null, firstPic = null;
                while (off + 10 <= end) {
                    const id0 = body[off], id1 = body[off+1], id2 = body[off+2], id3 = body[off+3];
                    if (!(id0 >= 65 && id0 <= 90) || !(id1 >= 65 && id1 <= 90) || !(id2 >= 65 && id2 <= 90) || !(id3 >= 65 && id3 <= 90)) break; // padding / end
                    const fid = String.fromCharCode(id0, id1, id2, id3);
                    const fsize = ver === 4 ? syncsafe(body[off+4], body[off+5], body[off+6], body[off+7]) : ((body[off+4]<<24)|(body[off+5]<<16)|(body[off+6]<<8)|body[off+7]);
                    if (fsize <= 0 || off + 10 + fsize > end) break;
                    let fdata = body.subarray(off + 10, off + 10 + fsize);
                    const fflags = ver === 4 ? body[off+9] : 0;
                    if (ver === 4 && (fflags & 0x02)) {
                        const d = new Uint8Array(fdata.length);
                        let j = 0;
                        for (let i = 0; i < fdata.length; i++) { d[j++] = fdata[i]; if (fdata[i] === 0xFF && i + 1 < fdata.length && fdata[i+1] === 0x00) i++; }
                        fdata = d.subarray(0, j);
                    }
                    if (fid === 'TIT2') out.title = dec(fdata.subarray(1), fdata[0]);
                    else if (fid === 'TPE1') out.artist = dec(fdata.subarray(1), fdata[0]);
                    else if (fid === 'TALB') out.album = dec(fdata.subarray(1), fdata[0]);
                    else if (fid === 'APIC' && !bestPic) {
                        let p = 1;
                        let mime = '';
                        while (p < fdata.length && fdata[p] !== 0) { mime += String.fromCharCode(fdata[p]); p++; }
                        p++; // 跳过 0
                        const picType = fdata[p]; p++;
                        // description（按编码找终止符）
                        if (fdata[0] === 1 || fdata[0] === 2) { while (p + 1 < fdata.length && !(fdata[p] === 0 && fdata[p+1] === 0)) p += 2; p += 2; }
                        else { while (p < fdata.length && fdata[p] !== 0) p++; p++; }
                        const pic = fdata.subarray(p);
                        if (pic.length > 100) {
                            const item = { mime, data: pic };
                            if (picType === 3) bestPic = item;
                            else if (!firstPic) firstPic = item;
                        }
                    }
                    off += 10 + fsize;
                }
                out.picture = bestPic || firstPic;
                return out;
            } catch (e) { return null; }
        }

        function musicParseFlac(u8) {
            try {
                if (u8.length < 8 || u8[0] !== 0x66 || u8[1] !== 0x4C || u8[2] !== 0x61 || u8[3] !== 0x43) return null; // 'fLaC'
                const dec = new TextDecoder('utf-8');
                let off = 4;
                const out = {};
                let picture = null;
                while (off + 4 <= u8.length) {
                    const head = u8[off];
                    const isLast = head & 0x80;
                    const type = head & 0x7f;
                    const len = (u8[off+1] << 16) | (u8[off+2] << 8) | u8[off+3];
                    const data = u8.subarray(off + 4, Math.min(off + 4 + len, u8.length));
                    if (type === 6 && data.length > 30) {
                        // PICTURE
                        let p = 4; // 跳过 picture type u32
                        const mimeLen = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += 4;
                        const mime = dec.decode(data.subarray(p, p + mimeLen)); p += mimeLen;
                        const descLen = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += descLen + 4 + 16; // desc + w/h/depth/colors
                        const dLen = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += 4;
                        if (dLen > 100 && p + dLen <= data.length + 1) picture = { mime, data: data.subarray(p, p + dLen) };
                    } else if (type === 4 && !out.artist) {
                        // VORBIS_COMMENT
                        let p = 0;
                        const vlen = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += 4 + vlen;
                        const count = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += 4;
                        for (let i = 0; i < count && p + 4 <= data.length; i++) {
                            const cl = (data[p]<<24)|(data[p+1]<<16)|(data[p+2]<<8)|data[p+3]; p += 4;
                            const kv = dec.decode(data.subarray(p, Math.min(p + cl, data.length))); p += cl;
                            const eq = kv.indexOf('=');
                            if (eq > 0) {
                                const k = kv.slice(0, eq).toUpperCase();
                                const v = kv.slice(eq + 1);
                                if (k === 'TITLE') out.title = v;
                                else if (k === 'ARTIST') out.artist = v;
                                else if (k === 'ALBUM') out.album = v;
                            }
                        }
                    }
                    off += 4 + len;
                    if (isLast || (picture && out.title)) break;
                }
                out.picture = picture;
                return out;
            } catch (e) { return null; }
        }

        // ---- 播放列表面板 ----
        function musicTogglePlaylist() {
            const panel = document.getElementById('musicPlaylistPanel');
            if (panel.style.display === 'none') { musicRenderPlaylist(); panel.style.display = 'flex'; }
            else panel.style.display = 'none';
        }
        function musicRenderPlaylist() {
            const list = document.getElementById('musicPlList');
            document.getElementById('musicPlCount').textContent = musicQueue.length + ' 首';
            if (!musicQueue.length) { list.innerHTML = '<div class="media-scan-empty">队列为空</div>'; return; }
            list.innerHTML = musicQueue.map((f, i) => {
                const artist = (f.tags && f.tags.artist) || '';
                return `<div class="music-pl-item ${f.id===musicCurrentId?'current':''}" onclick="musicPlay('${f.id}')">
                    <span class="music-pl-idx">${i+1}</span>
                    <span class="music-pl-name">${f.customName || (f.tags && f.tags.title) || f.name}</span>
                    <span class="music-pl-artist">${artist}</span>
                </div>`;
            }).join('');
            const cur = list.querySelector('.music-pl-item.current');
            if (cur) cur.scrollIntoView({ block: 'center' });
        }

        // ---- 播放详情弹窗 + LRC 歌词 ----
        function musicNowOpen() {
            if (!musicCurrentId) { showToast('先播放一首歌曲', 'info'); return; }
            const f = musicData.files.find(x => x.id === musicCurrentId);
            if (!f) return;
            document.getElementById('musicNowTitle').textContent = f.customName || (f.tags && f.tags.title) || f.name;
            const artist = (f.tags && f.tags.artist) || '';
            const album = (f.tags && f.tags.album) || '';
            document.getElementById('musicNowMeta').textContent = [artist, album].filter(Boolean).join(' - ');
            musicPaintCovers(f);
            musicUpdateProgressUI();
            musicUpdatePlayIcons();
            musicApplyModeUI();
            document.getElementById('musicNowModal').style.display = 'flex';
            musicLoadLrc(f);
        }
        function musicNowClose() {
            document.getElementById('musicNowModal').style.display = 'none';
        }
        async function musicLoadLrc(f) {
            musicLrc = []; musicLrcIdx = -1;
            const inner = document.getElementById('musicLrcInner');
            if (!f.hasLrc) { inner.innerHTML = '<div class="music-lrc-empty">暂无歌词</div>'; return; }
            try {
                const j = await fetch('/api/media/lrc?id=' + f.id).then(r => r.json());
                if (!j.success) { inner.innerHTML = '<div class="music-lrc-empty">暂无歌词</div>'; return; }
                musicLrcRender(musicLrcParse(j.lrc));
            } catch (e) { inner.innerHTML = '<div class="music-lrc-empty">歌词加载失败</div>'; }
        }
        function musicLrcParse(text) {
            const lines = [];
            const stamp = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
            for (const raw of text.split(/\r?\n/)) {
                stamp.lastIndex = 0;
                const times = [];
                let m;
                while ((m = stamp.exec(raw)) !== null) {
                    const min = parseInt(m[1], 10);
                    const sec = parseInt(m[2], 10);
                    let ms = m[3] ? parseInt(m[3], 10) : 0;
                    if (m[3] && m[3].length === 1) ms *= 100;
                    else if (m[3] && m[3].length === 2) ms *= 10;
                    times.push(min * 60 + sec + ms / 1000);
                }
                const content = raw.replace(stamp, '').trim();
                if (times.length && content) times.forEach(t => lines.push({ t, text: content }));
            }
            lines.sort((a, b) => a.t - b.t);
            return lines;
        }
        function musicLrcRender(lines) {
            musicLrc = lines; musicLrcIdx = -1;
            const inner = document.getElementById('musicLrcInner');
            if (!lines.length) { inner.innerHTML = '<div class="music-lrc-empty">暂无歌词</div>'; return; }
            inner.innerHTML = lines.map((l, i) => `<div class="music-lrc-line" data-i="${i}" data-t="${l.t}">${l.text}</div>`).join('');
        }
        function musicLrcTick() {
            if (!musicLrc.length) return;
            const cur = musicAudio.currentTime || 0;
            let idx = -1;
            for (let i = 0; i < musicLrc.length; i++) { if (musicLrc[i].t <= cur) idx = i; else break; }
            if (idx === musicLrcIdx) return;
            const inner = document.getElementById('musicLrcInner');
            const prev = inner.querySelector('.music-lrc-line.active');
            if (prev) prev.classList.remove('active');
            musicLrcIdx = idx;
            if (idx >= 0) {
                const el = inner.querySelector(`.music-lrc-line[data-i="${idx}"]`);
                if (el) {
                    el.classList.add('active');
                    // 居中滚动
                    const wrap = document.getElementById('musicNowLyrics');
                    wrap.scrollTop = el.offsetTop - wrap.clientHeight / 2 + el.clientHeight / 2;
                }
            }
        }

        // ============ 本地视频播放器 ============
        let videoData = { categories: [{id:'default',name:'未分类'}], files: [], scanRoots: [], activeCat: '__all__', search: '' };
        let videoCurrentId = null;
        let videoQueue = [];
        let videoTabActive = false;
        let videoServerOk = false;
        let videoThumbObserver = null;
        let videoThumbInProgress = new Set();

        function videoInit() {
            videoBindControls();
            fetch('/api/media').then(r => r.json()).then(j => {
                if (j.success) {
                    videoServerOk = true;
                    document.getElementById('videoTabBtn').style.display = '';
                    videoLoadFromServer(j.data);
                    videoInitObserver();
                    videoRender();
                }
            }).catch(() => {});
        }

        function videoTabOn() {
            videoTabActive = true;
            if (!videoThumbObserver) videoInitObserver();
        }
        function videoTabOff() {
            videoTabActive = false;
            const vp = document.getElementById('videoPlayerEl');
            if (vp) { vp.pause(); vp.removeAttribute('src'); }
        }

        function videoLoadFromServer(lib) {
            const cats = (lib.categories && lib.categories.video) || [{id:'default',name:'未分类'}];
            const files = (lib.files || []).filter(f => f.type === 'video');
            videoData.categories = cats;
            videoData.files = files;
            videoData.scanRoots = ((lib.scanRoots && lib.scanRoots.video) || []).map(mediaNormRoot);
        }

        function videoSyncToServer() {
            const payload = {
                categories: { video: videoData.categories },
                files: videoData.files.map(f => ({ id: f.id, categoryId: f.categoryId, customName: f.customName || '', duration: f.duration, thumbFile: f.thumbFile }))
            };
            fetch('/api/media', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        }

        function videoInitObserver() {
            videoThumbObserver = new IntersectionObserver((entries) => {
                entries.forEach(e => {
                    if (!e.isIntersecting) return;
                    const img = e.target;
                    const id = img.dataset.id;
                    if (img.dataset.tried) return;
                    img.dataset.tried = '1';
                    videoThumbLoad(id);
                });
            }, { rootMargin: '200px' });
        }

        function videoRender() {
            const search = (document.getElementById('videoSearch')?.value || '').toLowerCase();
            const cat = videoData.activeCat;
            let list = videoData.files;
            if (cat !== '__all__') list = list.filter(f => (f.categoryId || 'default') === cat);
            if (search) list = list.filter(f => f.name.toLowerCase().includes(search) || (f.dir||'').toLowerCase().includes(search) || (f.customName||'').toLowerCase().includes(search) || (f.tags||[]).some(t => String(t).toLowerCase().includes(search)));
            videoQueue = list;

            // 分类侧栏
            const catList = document.getElementById('videoCatList');
            const allCount = videoData.files.length;
            let html = `<div class="media-cat-item ${cat==='__all__'?'active':''}" onclick="videoSelectCategory('__all__')"><span>全部</span><span class="media-cat-count">${allCount}</span></div>`;
            for (const c of videoData.categories) {
                const cnt = videoData.files.filter(f => (f.categoryId||'default') === c.id).length;
                const bound = videoData.scanRoots.filter(r => r.categoryId === c.id);
                const bindBadge = bound.length ? `<span class="media-cat-bind" title="绑定扫描目录：&#10;${escapeHtml(bound.map(r => r.path).join('\n'))}">📁${bound.length}</span>` : '';
                const canDel = c.id !== 'default';
                html += `<div class="media-cat-item ${cat===c.id?'active':''}" onclick="videoSelectCategory('${c.id}')" oncontextmenu="event.preventDefault();videoRenameCategory('${c.id}')"><span>${escapeHtml(c.name)}</span>${bindBadge}<span class="media-cat-count">${cnt}</span><span class="media-cat-acts">${canDel?`<span class="media-cat-del" title="删除分类" onclick="event.stopPropagation();videoDeleteCategory('${c.id}')">×</span>`:''}<span class="media-cat-edit" title="重命名分类" onclick="event.stopPropagation();videoRenameCategory('${c.id}')">✏</span></span></div>`;
            }
            catList.innerHTML = html;

            // 视频卡片网格
            const grid = document.getElementById('videoGrid');
            if (list.length === 0) {
                grid.innerHTML = '';
                document.getElementById('videoEmpty').style.display = 'flex';
            } else {
                document.getElementById('videoEmpty').style.display = 'none';
                grid.innerHTML = list.map(f => {
                    const dur = f.duration ? videoFmtTime(f.duration) : '';
                    const sz = videoFmtSize(f.size);
                    const playable = ['.mp4','.mov','.webm','.m4v'].includes(f.ext);
                    const tags = (f.tags || []).slice(0, 2);
                    const tagsHtml = (f.tags && f.tags.length) ? `<div class="video-card-tags">${tags.map(t => `<span class="vctag">${escapeHtml(t)}</span>`).join('')}${f.tags.length > 2 ? `<span class="vctag">+${f.tags.length - 2}</span>` : ''}</div>` : '';
                    return `<div class="video-card ${videoCurrentId===f.id?'playing':''}" data-vid="${f.id}" onclick="videoPlay('${f.id}')" oncontextmenu="event.preventDefault();videoShowMenu(event,'${f.id}')" title="点击播放，右键更多操作">
                        <div class="video-thumb">
                            ${f.thumbFile ? `<img class="video-thumb-img" src="/media_thumb?id=${f.id}" alt="${f.name}">` : `<img class="video-thumb-img" data-id="${f.id}" style="display:none;" alt=""><div class="video-thumb-ph">▶</div>`}
                            ${dur ? `<span class="video-thumb-dur">${dur}</span>` : ''}
                        </div>
                        <div class="video-card-info">
                            <div class="video-card-title">${f.customName || f.name}</div>
                            ${tagsHtml}
                            <div class="video-card-meta"><span>${sz}</span>${playable?'':'<span style="color:#f59e0b;">需外部播放</span>'}</div>
                        </div>
                    </div>`;
                }).join('');
                // 观察未生成缩略图的图片
                if (videoThumbObserver) {
                    grid.querySelectorAll('img.video-thumb-img[data-id]').forEach(img => videoThumbObserver.observe(img));
                }
            }
            document.getElementById('videoCount').textContent = `共 ${list.length} 个`;
        }

        function videoSelectCategory(id) { videoData.activeCat = id; videoRender(); }
        function videoAddCategory() {
            const name = prompt('输入分类名称：');
            if (!name || !name.trim()) return;
            videoData.categories.push({ id:'c_'+Date.now().toString(36), name:name.trim() });
            videoSyncToServer(); videoRender();
        }
        function videoRenameCategory(id) {
            const c = videoData.categories.find(x => x.id === id);
            if (!c) return;
            const name = prompt('重命名分类：', c.name);
            if (!name || !name.trim()) return;
            c.name = name.trim(); videoSyncToServer(); videoRender();
        }
        function videoDeleteCategory(id) {
            if (!confirm('确认删除该分类？分类内视频将归入默认分类')) return;
            videoData.categories = videoData.categories.filter(c => c.id !== id);
            videoData.files.forEach(f => { if (f.categoryId === id) f.categoryId = 'default'; });
            videoData.scanRoots.forEach(r => { if (r.categoryId === id) r.categoryId = 'default'; });
            if (videoData.activeCat === id) videoData.activeCat = '__all__';
            videoSyncToServer(); videoRender();
        }

        function videoShowMenu(e, id) {
            const f = videoData.files.find(x => x.id === id);
            if (!f) return;
            const cur = f.categoryId || 'default';
            mediaShowMenu(e.clientX, e.clientY, [
                { label: '▶ 播放', act: 'video-play', id },
                { type: 'sep' },
                { label: '移动到分类', type: 'sub', items: [
                    ...videoData.categories.map(c => ({ label: (c.id === cur ? '✓ ' : '') + escapeHtml(c.name), act: 'video-setcat', id: id + '|' + c.id, active: c.id === cur })),
                    { label: '＋ 新建分类…', act: 'video-newcat', id }
                ] },
                { type: 'sep' },
                { label: '重新截取封面', act: 'video-thumb', id }
            ]);
        }
        function videoSetCategory(payload) {
            const i = payload.lastIndexOf('|');
            const f = videoData.files.find(x => x.id === payload.slice(0, i));
            if (!f) return;
            f.categoryId = payload.slice(i + 1);
            videoSyncToServer(); videoRender();
            const c = videoData.categories.find(x => x.id === f.categoryId);
            showToast('已移动到分类：' + (c ? c.name : '未分类'), 'success', 1500);
        }
        function videoNewCatAndAssign(fileId) {
            const name = prompt('输入新分类名称：');
            if (!name || !name.trim()) return;
            const cid = 'c_' + Date.now().toString(36);
            videoData.categories.push({ id: cid, name: name.trim() });
            const f = videoData.files.find(x => x.id === fileId);
            if (f) f.categoryId = cid;
            videoSyncToServer(); videoRender();
            showToast('已创建分类「' + name.trim() + '」并移入', 'success', 1500);
        }

        function videoPlay(id) {
            const f = videoData.files.find(x => x.id === id);
            if (!f) return;
            if (!['.mp4', '.mov', '.webm', '.m4v'].includes(f.ext)) { showToast('该格式浏览器不支持在线播放，请外部打开', 'error'); return; }
            videoCurrentId = id;
            const v = document.getElementById('videoPlayerEl');
            // 有封面帧先显示 poster，避免打开时黑屏等待首帧解码
            v.poster = f.thumbFile ? ('/media_thumb?id=' + id) : '';
            v.src = '/media_file?id=' + id;
            v.playbackRate = videoSavedRate;
            v.play().catch(() => {}); // 尽早触发加载与解码，不等下方 DOM 渲染
            document.getElementById('videoPlayerTitle').textContent = f.customName || f.name;
            videoFillInfo(f);
            const inline = document.getElementById('videoPlayerInline');
            inline.style.display = 'block';
            document.querySelector('#tab-video .media-main').classList.add('player-open');
            // 重置进度 UI
            document.getElementById('videoFill').style.width = '0%';
            document.getElementById('videoBuf').style.width = '0%';
            document.getElementById('videoTimeText').textContent = '00:00 / 00:00';
            document.getElementById('videoRateBadge').classList.remove('show');
            videoUpdatePlayingCard();
            videoShowControls();
            vdmLoadForVideo(id);
            vdmStart();
            inline.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            videoPrefetchNext();
        }
        // 预取队列下一个视频的头部（元数据+起始数据）进浏览器媒体缓存（响应头 immutable 可缓存），
        // 切换播放时直接命中缓存近乎秒开；只拉不播，元数据到手即释放
        const videoPrefetched = new Set();
        function videoPrefetchNext() {
            const queue = (videoQueue && videoQueue.length) ? videoQueue : videoData.files;
            const playable = queue.filter(f => ['.mp4', '.mov', '.webm', '.m4v'].includes(f.ext));
            if (!playable.length) return;
            let idx = playable.findIndex(f => f.id === videoCurrentId);
            idx = (idx + 1) % playable.length;
            const nid = playable[idx].id;
            if (nid === videoCurrentId || videoPrefetched.has(nid)) return;
            videoPrefetched.add(nid);
            const pv = document.createElement('video');
            pv.muted = true; pv.preload = 'auto';
            pv.src = '/media_file?id=' + nid;
            const release = () => { try { pv.removeAttribute('src'); pv.load(); } catch (e) {} };
            pv.addEventListener('loadedmetadata', release);
            setTimeout(release, 10000); // 兜底：慢速大文件 10s 后释放
        }
        function videoClosePlayer() {
            const v = document.getElementById('videoPlayerEl');
            v.pause(); v.removeAttribute('src');
            document.getElementById('videoPlayerInline').style.display = 'none';
            document.querySelector('#tab-video .media-main').classList.remove('player-open');
            document.getElementById('videoSpeedMenu').classList.remove('show');
            document.getElementById('videoRateBadge').classList.remove('show');
            if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
            vdmStop();
            videoCurrentId = null;
            videoUpdatePlayingCard();
        }
        function videoUpdatePlayingCard() {
            document.querySelectorAll('#videoGrid .video-card').forEach(el => {
                el.classList.toggle('playing', el.dataset.vid === videoCurrentId);
            });
        }

        // ---- 视频信息区（标题 / 标签 / 简介，B站式） ----
        function videoCurrentFile() { return videoData.files.find(x => x.id === videoCurrentId); }

        function videoSaveMetaFields(fields) {
            if (!videoCurrentId) return;
            fetch('/api/media/file-meta', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(Object.assign({ id: videoCurrentId }, fields)) })
                .catch(() => showToast('信息保存失败', 'error'));
        }

        function videoFillInfo(f) {
            document.getElementById('vibTitle').textContent = f.customName || f.name;
            const desc = document.getElementById('vibDesc');
            desc.textContent = f.desc || f.name;   // 简介默认取视频名称
            videoRenderTags(f);
        }

        function videoRenderTags(f) {
            const box = document.getElementById('vibTags');
            const tags = f.tags || [];
            box.innerHTML = tags.map((t, i) =>
                `<span class="vib-tag">${escapeHtml(t)}<span class="vib-tag-x" data-i="${i}" title="删除标签">×</span></span>`).join('');
        }

        function videoInitInfoBar() {
            const desc = document.getElementById('vibDesc');
            // 简介：聚焦时若未自定义则清空默认名占位，失焦保存
            desc.addEventListener('focus', () => {
                const f = videoCurrentFile();
                if (f && !f.desc) desc.textContent = '';
            });
            desc.addEventListener('blur', () => {
                const f = videoCurrentFile();
                if (!f) return;
                const text = desc.textContent.trim();
                f.desc = text;
                videoSaveMetaFields({ desc: text });
                if (!text) desc.textContent = f.name;   // 空简介回显默认名
            });
            // 添加标签（支持逗号批量）
            document.getElementById('vibTagAdd').addEventListener('click', () => {
                const f = videoCurrentFile();
                if (!f) return;
                const input = prompt('输入标签，多个用逗号分隔：');
                if (input === null) return;
                const add = input.split(/[,，]/).map(s => s.trim()).filter(Boolean);
                if (!add.length) return;
                f.tags = Array.from(new Set([...(f.tags || []), ...add])).slice(0, 20);
                videoSaveMetaFields({ tags: f.tags });
                videoRenderTags(f);
                videoRender();
                showToast('已添加标签：' + add.join('、'), 'success', 1500);
            });
            // 删除标签（事件委托）
            document.getElementById('vibTags').addEventListener('click', (e) => {
                const x = e.target.closest('.vib-tag-x');
                if (!x) return;
                const f = videoCurrentFile();
                if (!f) return;
                const removed = (f.tags || [])[parseInt(x.dataset.i)];
                f.tags.splice(parseInt(x.dataset.i), 1);
                videoSaveMetaFields({ tags: f.tags });
                videoRenderTags(f);
                videoRender();
                showToast('已移除标签：' + removed, 'info', 1200);
            });
        }

        // ---- B站风格自定义控制 ----
        let videoControlsHideTimer = null;
        let videoSavedVol = parseFloat(localStorage.getItem('videoVol')); if (isNaN(videoSavedVol)) videoSavedVol = 1;
        let videoSavedRate = 1;
        const videoSpeeds = [0.5, 0.75, 1, 1.25, 1.5, 2];
        let videoSuppressClick = false;

        // B站风格线性图标
        const V_ICON = {
            play: '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M8 5.14v14l11-7-11-7z" fill="currentColor"/></svg>',
            pause: '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z" fill="currentColor"/></svg>',
            volHigh: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M3 9v6h4l5 5V4L7 9H3z" fill="currentColor"/><path d="M16 8.1a5 5 0 010 7.8M18.5 5.5a8.5 8.5 0 010 13" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>',
            volLow: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M3 9v6h4l5 5V4L7 9H3z" fill="currentColor"/><path d="M16 8.1a5 5 0 010 7.8" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>',
            volMute: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M3 9v6h4l5 5V4L7 9H3z" fill="currentColor"/><path d="M16.5 9.5l5 5m0-5l-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none"/></svg>'
        };

        // 播放器时间码（B站补零格式 00:00，超一小时 H:MM:SS）
        function videoPadTime(sec) {
            if (!sec || !isFinite(sec) || sec < 0) sec = 0;
            const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
            const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
            return h > 0 ? h + ':' + mm + ':' + ss : mm + ':' + ss;
        }

        function videoBindControls() {
            const v = document.getElementById('videoPlayerEl');
            const stage = document.getElementById('videoStage');

            v.addEventListener('play', videoUpdatePlayUI);
            v.addEventListener('pause', videoUpdatePlayUI);
            v.addEventListener('waiting', () => document.getElementById('videoSpinner').style.display = 'block');
            v.addEventListener('playing', () => document.getElementById('videoSpinner').style.display = 'none');
            v.addEventListener('canplay', () => document.getElementById('videoSpinner').style.display = 'none');
            v.addEventListener('loadedmetadata', () => { v.playbackRate = videoSavedRate; videoUpdateProgressUI(); });
            v.addEventListener('timeupdate', videoUpdateProgressUI);
            v.addEventListener('progress', videoUpdateBufferUI);
            v.addEventListener('ended', () => videoQueueStep(1));
            v.addEventListener('error', () => { document.getElementById('videoSpinner').style.display = 'none'; if (videoCurrentId) showToast('视频无法播放：格式不支持或文件已移动', 'error'); });

            // 进度条（拖拽 + 悬停预览）
            mediaBindTrack(document.getElementById('videoProgress'), document.getElementById('videoFill'),
                f => { if (v.duration && isFinite(v.duration)) v.currentTime = f * v.duration; },
                document.getElementById('videoProgressTip'),
                f => videoPadTime((v.duration || 0) * f));

            // 音量条
            mediaBindTrack(document.getElementById('videoVolSlider'), document.getElementById('videoVolFill'), f => videoSetVolume(f), null, null, { live: true });
            videoSetVolume(videoSavedVol);
            document.getElementById('videoVolIcon').addEventListener('click', videoMuteToggle);

            // 播放/暂停按钮 + 中央按钮
            document.getElementById('videoPlayBtn').addEventListener('click', videoTogglePlay);
            document.getElementById('videoCenterToggle').addEventListener('click', videoTogglePlay);

            // 点击画面切换播放（长按 3x 结束后抑制一次），双击全屏
            stage.addEventListener('click', (e) => { if (e.target === v && !videoSuppressClick) videoTogglePlay(); });
            stage.addEventListener('dblclick', (e) => { if (e.target === v) videoToggleFullscreen(); });

            // 长按画面 3 倍速快进（B站特色交互）
            let lpTimer = null, lpActive = false;
            stage.addEventListener('pointerdown', (e) => {
                if (e.button !== 0 || e.target !== v || !v.src || v.paused || v.ended) return;
                lpTimer = setTimeout(() => {
                    lpActive = true;
                    v.playbackRate = 3;
                    document.getElementById('videoRateBadge').classList.add('show');
                }, 450);
            });
            const lpEnd = () => {
                clearTimeout(lpTimer);
                if (lpActive) {
                    lpActive = false;
                    v.playbackRate = videoSavedRate;
                    document.getElementById('videoRateBadge').classList.remove('show');
                    videoSuppressClick = true;
                    setTimeout(() => { videoSuppressClick = false; }, 250);
                }
            };
            stage.addEventListener('pointerup', lpEnd);
            stage.addEventListener('pointercancel', lpEnd);
            stage.addEventListener('pointerleave', lpEnd);

            // 倍速菜单
            const menu = document.getElementById('videoSpeedMenu');
            menu.innerHTML = [...videoSpeeds].reverse().map(s => `<div class="video-speed-item" data-s="${s}">${s === 1 ? '正常' : s + 'x'}</div>`).join('');
            menu.addEventListener('click', (e) => {
                const item = e.target.closest('.video-speed-item');
                if (!item) return;
                videoSetRate(parseFloat(item.dataset.s));
                menu.classList.remove('show');
            });
            document.getElementById('videoSpeedBtn').addEventListener('click', (e) => { e.stopPropagation(); menu.classList.toggle('show'); });
            document.addEventListener('click', (e) => {
                if (!menu.contains(e.target) && !e.target.closest('#videoSpeedBtn')) menu.classList.remove('show');
            });

            // 循环播放开关（记忆状态）
            const loopBtn = document.getElementById('videoLoopBtn');
            v.loop = localStorage.getItem('videoLoop') === '1';
            loopBtn.classList.toggle('vc-active', v.loop);
            loopBtn.addEventListener('click', () => {
                v.loop = !v.loop;
                localStorage.setItem('videoLoop', v.loop ? '1' : '0');
                loopBtn.classList.toggle('vc-active', v.loop);
                showToast(v.loop ? '已开启循环播放' : '已关闭循环播放', 'info', 1200);
            });

            // 画中画
            const pipBtn = document.getElementById('videoPipBtn');
            if (document.pictureInPictureEnabled) {
                pipBtn.addEventListener('click', videoTogglePip);
            } else {
                pipBtn.style.opacity = '.4'; pipBtn.title = '当前浏览器不支持画中画';
            }

            // 全屏
            document.getElementById('videoFsBtn').addEventListener('click', videoToggleFullscreen);

            // 控制栏显隐：鼠标移动显示，播放中停顿 2.5s 自动隐藏
            stage.addEventListener('mousemove', videoShowControls);
            stage.addEventListener('mouseleave', () => { if (!v.paused) videoHideControls(); });
            // 触屏：触摸播放器即显示控制栏（同样 2.5s 后自动隐藏）
            stage.addEventListener('touchstart', () => videoShowControls(), { passive: true });
            // 移动端长按视频卡片呼出右键菜单（播放 / 移动分类 / 重截封面）
            mediaBindLongPress(document.getElementById('videoGrid'), '.video-card', (x, y, el) => videoShowMenu({ clientX: x, clientY: y }, el.dataset.vid));

            // 初始化按钮图标与倍速高亮
            videoSetRate(videoSavedRate);
            videoUpdatePlayUI();
            vdmInitUI();
            videoInitInfoBar();

            // 键盘快捷键
            document.addEventListener('keydown', videoKeydown);
        }

        function videoTogglePlay() {
            const v = document.getElementById('videoPlayerEl');
            if (!v.src) return;
            if (v.paused) v.play().catch(() => {}); else v.pause();
        }
        function videoUpdatePlayUI() {
            const v = document.getElementById('videoPlayerEl');
            const playing = !v.paused && !v.ended;
            document.getElementById('videoPlayBtn').innerHTML = playing ? V_ICON.pause : V_ICON.play;
            document.getElementById('videoCenterToggle').innerHTML = playing ? V_ICON.pause : V_ICON.play;
            document.getElementById('videoCenterToggle').style.display = playing ? 'none' : 'flex';
            if (playing) videoScheduleHide(); else videoShowControls();
        }
        function videoUpdateProgressUI() {
            const v = document.getElementById('videoPlayerEl');
            if (!v.duration || !isFinite(v.duration)) return;
            document.getElementById('videoFill').style.width = (v.currentTime / v.duration * 100) + '%';
            document.getElementById('videoTimeText').textContent = videoPadTime(v.currentTime) + ' / ' + videoPadTime(v.duration);
        }
        function videoUpdateBufferUI() {
            const v = document.getElementById('videoPlayerEl');
            try {
                if (v.buffered.length && v.duration && isFinite(v.duration)) {
                    document.getElementById('videoBuf').style.width = (v.buffered.end(v.buffered.length - 1) / v.duration * 100) + '%';
                }
            } catch (e) {}
        }
        function videoSetVolume(vol) {
            const v = document.getElementById('videoPlayerEl');
            vol = Math.min(1, Math.max(0, vol));
            v.volume = vol;
            if (vol > 0) v.muted = false;
            videoSavedVol = vol;
            localStorage.setItem('videoVol', String(vol));
            document.getElementById('videoVolFill').style.width = (vol * 100) + '%';
            videoUpdateVolIcon();
        }
        function videoMuteToggle() {
            const v = document.getElementById('videoPlayerEl');
            v.muted = !v.muted;
            videoUpdateVolIcon();
        }
        function videoUpdateVolIcon() {
            const v = document.getElementById('videoPlayerEl');
            const vol = (v.muted || v.volume === 0) ? 0 : v.volume;
            document.getElementById('videoVolIcon').innerHTML = vol === 0 ? V_ICON.volMute : vol < 0.5 ? V_ICON.volLow : V_ICON.volHigh;
        }
        function videoSetRate(rate) {
            const v = document.getElementById('videoPlayerEl');
            videoSavedRate = rate;
            v.playbackRate = rate;
            document.getElementById('videoSpeedBtn').textContent = rate === 1 ? '倍速' : rate + 'x';
            document.querySelectorAll('#videoSpeedMenu .video-speed-item').forEach(el => el.classList.toggle('active', parseFloat(el.dataset.s) === rate));
        }
        function videoTogglePip() {
            const v = document.getElementById('videoPlayerEl');
            if (document.pictureInPictureElement) {
                document.exitPictureInPicture().catch(() => {});
            } else if (v.src) {
                v.requestPictureInPicture().catch(() => showToast('画中画启动失败', 'error'));
            }
        }
        function videoToggleFullscreen() {
            const stage = document.getElementById('videoStage');
            if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
            else stage.requestFullscreen().catch(() => {});
        }
        function videoShowControls() {
            document.getElementById('videoStage').classList.remove('vc-hidden');
            videoScheduleHide();
        }
        function videoHideControls() {
            document.getElementById('videoStage').classList.add('vc-hidden');
        }
        function videoScheduleHide() {
            clearTimeout(videoControlsHideTimer);
            const v = document.getElementById('videoPlayerEl');
            if (v.paused) return;
            videoControlsHideTimer = setTimeout(() => {
                if (!document.getElementById('videoPlayerEl').paused && !document.getElementById('videoSpeedMenu').classList.contains('show')) videoHideControls();
            }, 2500);
        }
        function videoKeydown(e) {
            const inline = document.getElementById('videoPlayerInline');
            if (!inline || inline.style.display === 'none') return;
            const videoTab = document.getElementById('tab-video');
            if (!videoTab || !videoTab.classList.contains('active')) return;
            const tag = document.activeElement ? document.activeElement.tagName : '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (document.activeElement && document.activeElement.isContentEditable) return;
            const v = document.getElementById('videoPlayerEl');
            switch (e.key) {
                case ' ': e.preventDefault(); videoTogglePlay(); break;
                case 'ArrowRight': e.preventDefault(); v.currentTime = Math.min(v.duration || 0, v.currentTime + 5); videoShowControls(); break;
                case 'ArrowLeft': e.preventDefault(); v.currentTime = Math.max(0, v.currentTime - 5); videoShowControls(); break;
                case 'ArrowUp': e.preventDefault(); videoSetVolume((v.muted ? 0 : v.volume) + 0.1); break;
                case 'ArrowDown': e.preventDefault(); videoSetVolume(v.volume - 0.1); break;
                case 'm': case 'M': videoMuteToggle(); break;
                case 'f': case 'F': videoToggleFullscreen(); break;
                case 'Escape': if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); break;
            }
        }
        function videoQueueStep(dir) {
            const queue = (videoQueue && videoQueue.length) ? videoQueue : videoData.files;
            const playable = queue.filter(f => ['.mp4', '.mov', '.webm', '.m4v'].includes(f.ext));
            if (!playable.length) return;
            let idx = playable.findIndex(f => f.id === videoCurrentId);
            idx = (idx + dir + playable.length) % playable.length;
            videoPlay(playable[idx].id);
        }

        function videoThumbLoad(id) {
            const f = videoData.files.find(x => x.id === id);
            if (!f) return;
            const img = document.querySelector(`img.video-thumb-img[data-id="${id}"]`);
            if (!img) return;
            if (f.thumbFile) {
                img.src = '/media_thumb?id=' + id;
                img.style.display = '';
                if (img.previousElementSibling) img.previousElementSibling.style.display = 'none';
                return;
            }
            // 大于 2GB 跳过
            if (f.size > 2 * 1024 * 1024 * 1024) return;
            if (videoThumbInProgress.has(id)) return;
            videoThumbInProgress.add(id);
            videoGenThumb(f, img);
        }

        // 右键：重新截取关键帧封面（覆盖旧的第一帧封面）
        function videoRegenThumb(id) {
            const f = videoData.files.find(x => x.id === id);
            if (!f) return;
            if (['.mkv', '.avi', '.flv', '.wmv', '.ts'].includes(f.ext)) { showToast('该格式浏览器无法解码，无法截取封面', 'error'); return; }
            if (f.size > 2 * 1024 * 1024 * 1024) { showToast('文件过大，无法截取封面', 'error'); return; }
            if (videoThumbInProgress.has(id)) { showToast('正在截取中，请稍候', 'info'); return; }
            videoThumbInProgress.add(id);
            const img = document.querySelector(`#videoGrid .video-card[data-vid="${id}"] img.video-thumb-img`);
            if (f.thumbFile) f.thumbFile = null; // 强制走关键帧生成流程
            videoGenThumb(f, img);
        }

        // 关键帧封面：在 10% / 32% / 55% / 78% 处采样 4 帧，
        // 按「画面细节(亮度方差) + 与前帧差异 - 过暗/过亮惩罚」打分，选最有代表性的一帧截图上传
        function videoGenThumb(file, imgEl) {
            const v = document.createElement('video');
            v.muted = true; v.preload = 'auto';
            v.src = '/media_file?id=' + file.id;

            const SMALL = 64;
            const cands = [];
            let times = [1];
            let idx = 0;
            let phase = 'sample'; // sample -> capture
            let duration = 0;
            let done = false;

            const finish = () => { done = true; try { v.removeAttribute('src'); v.load(); } catch(e) {} };

            v.addEventListener('error', () => {
                if (!done) { videoThumbInProgress.delete(file.id); finish(); }
            });

            v.addEventListener('loadedmetadata', () => {
                duration = (isFinite(v.duration) && v.duration > 0) ? v.duration : 0;
                if (duration > 0) times = [0.1, 0.32, 0.55, 0.78].map(p => Math.max(0.1, duration * p));
                v.currentTime = times[0];
            });

            v.addEventListener('seeked', () => {
                if (done) return;
                if (phase === 'sample') {
                    try { videoThumbSample(v, SMALL, cands); } catch (e) {}
                    idx++;
                    if (idx < times.length) { v.currentTime = times[idx]; }
                    else {
                        let best = times[0], bs = -Infinity;
                        for (const c of cands) if (c.score > bs) { bs = c.score; best = c.time; }
                        phase = 'capture';
                        v.currentTime = best;
                    }
                } else {
                    videoThumbCapture(v, file, imgEl, duration);
                    finish();
                }
            });

            // 超时保护：45s 未完成则释放，避免卡死占用队列
            setTimeout(() => {
                if (videoThumbInProgress.has(file.id)) { videoThumbInProgress.delete(file.id); if (!done) finish(); }
            }, 45000);
        }

        function videoThumbSample(v, size, cands) {
            const c = document.createElement('canvas');
            c.width = size; c.height = Math.max(1, Math.round(size * 9 / 16));
            const ctx = c.getContext('2d', { willReadFrequently: true });
            ctx.drawImage(v, 0, 0, c.width, c.height);
            const d = ctx.getImageData(0, 0, c.width, c.height).data;
            const n = d.length / 4;
            const lum = new Float32Array(n);
            let sum = 0, sum2 = 0;
            for (let i = 0; i < n; i++) {
                const l = 0.299 * d[i*4] + 0.587 * d[i*4+1] + 0.114 * d[i*4+2];
                lum[i] = l; sum += l; sum2 += l * l;
            }
            const mean = sum / n;
            const variance = Math.max(0, sum2 / n - mean * mean); // 画面细节/对比度
            let diff = 0;
            if (cands.length) {
                const prev = cands[cands.length - 1].lum;
                for (let i = 0; i < n; i++) diff += Math.abs(lum[i] - prev[i]);
                diff /= n; // 与前帧变化量（换头/转场更代表内容）
            }
            const score = variance + diff * 1.5 - Math.abs(mean - 115) * 0.6; // 惩罚黑屏/白屏
            cands.push({ time: v.currentTime, lum, score });
        }

        function videoThumbCapture(v, file, imgEl, duration) {
            try {
                const c = document.createElement('canvas');
                c.width = 320; c.height = 180;
                c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
                c.toBlob(blob => {
                    if (!blob) { videoThumbInProgress.delete(file.id); return; }
                    const fd = new FormData();
                    fd.append('id', file.id);
                    fd.append('file', blob, file.id + '.jpg');
                    fetch('/api/media/thumb', { method:'POST', body: fd })
                        .then(r => r.json()).then(j => {
                            if (j.success) {
                                file.thumbFile = j.thumbFile;
                                if (imgEl) {
                                    imgEl.src = '/media_thumb?id=' + file.id + '&t=' + Date.now();
                                    imgEl.style.display = '';
                                    if (imgEl.previousElementSibling) imgEl.previousElementSibling.style.display = 'none';
                                }
                            }
                        }).catch(()=>{}).finally(() => videoThumbInProgress.delete(file.id));
                }, 'image/jpeg', 0.7);
            } catch(e) { videoThumbInProgress.delete(file.id); }
            if (duration && isFinite(duration)) {
                file.duration = duration;
                fetch('/api/media/file-meta', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: file.id, duration: duration})});
            }
        }

        function videoOpenScan() { mediaScanOpen('video'); }
        function videoRescan() {
            if (!videoData.scanRoots.length) { mediaScanOpen('video'); return; }
            videoDoScan(videoData.scanRoots, true);
        }
        function videoDoScan(roots, isRescan) {
            showToast('正在扫描…', 'info', 1500);
            fetch('/api/media/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({roots, type:'video'}) })
                .then(r => r.json()).then(j => {
                    if (j.success) {
                        videoLoadFromServer(j.data);
                        videoRender();
                        showToast(`扫描完成，共 ${j.scanned} 个`, 'success');
                    } else { showToast('扫描失败：' + (j.error||''), 'error'); }
                }).catch(() => showToast('扫描请求失败', 'error'));
        }

        // ================= 弹幕 =================
        let vdmList = [];            // 当前视频弹幕 [{id,time,text,mode,color}]（按 time 升序）
        let vdmCursor = 0;           // 下一条待发射索引
        let vdmActive = [];          // 屏幕上活动弹幕
        let vdmScrollLanes = [];     // 滚动轨道占用 {start, w, dur}
        let vdmFixLanes = [];        // 顶部/底部轨道占用（until 时间）
        let vdmRafId = null;
        let vdmLoadedFor = null;
        let vdmLastNow = 0;          // 回退检测（循环重播兜底）
        let vdmMode = 1;             // 发送模式：1滚动 4底部 5顶部
        const VM_LANE_H = 34;       // 轨道高度
        const VM_FIX_DUR = 5;       // 顶部/底部停留秒数

        let vdmEnabled = localStorage.getItem('vdmEnabled') !== '0';
        let vdmSettings = { opacity: 1, area: 1, speed: 8 };
        try { Object.assign(vdmSettings, JSON.parse(localStorage.getItem('vdmSettings') || '{}')); } catch(e) {}

        function vdmPersistSettings() { localStorage.setItem('vdmSettings', JSON.stringify(vdmSettings)); }

        function vdmApplyLayerSize() {
            const layer = document.getElementById('danmakuLayer');
            if (layer) layer.style.height = (vdmSettings.area * 100) + '%';
        }

        function vdmLoadForVideo(fileId) {
            if (vdmLoadedFor === fileId) return;
            vdmLoadedFor = fileId;
            vdmList = []; vdmCursor = 0; vdmClearActive();
            fetch('/api/danmaku/list?id=' + fileId).then(r => r.json()).then(j => {
                if (j.success && vdmLoadedFor === fileId) { vdmList = j.data || []; vdmSyncCursor(); }
            }).catch(() => {});
        }

        function vdmReload() {
            if (!videoCurrentId) return;
            vdmLoadedFor = null;
            vdmLoadForVideo(videoCurrentId);
        }

        function vdmStart() {
            vdmApplyLayerSize();
            if (vdmRafId == null) vdmRafId = requestAnimationFrame(vdmTick);
        }

        function vdmStop() {
            if (vdmRafId != null) { cancelAnimationFrame(vdmRafId); vdmRafId = null; }
            vdmClearActive();
            vdmLoadedFor = null;
            vdmList = []; vdmCursor = 0; vdmLastNow = 0;
            const panel = document.getElementById('dmSettingPanel');
            if (panel) { panel.style.display = 'none'; document.getElementById('dmSettingBtn').classList.remove('active'); }
        }

        function vdmClearActive() {
            vdmActive.forEach(it => it.el.remove());
            vdmActive = []; vdmScrollLanes = []; vdmFixLanes = [];
        }

        function vdmSyncCursor() {
            const v = document.getElementById('videoPlayerEl');
            const now = v && isFinite(v.currentTime) ? v.currentTime : 0;
            let i = 0;
            while (i < vdmList.length && vdmList[i].time < now) i++;
            vdmCursor = i;
        }

        function vdmTick() {
            vdmRafId = requestAnimationFrame(vdmTick);
            const v = document.getElementById('videoPlayerEl');
            if (!v || !v.src) return;
            const now = v.currentTime;
            if (now < vdmLastNow - 0.5) { vdmClearActive(); vdmSyncCursor(); }  // 循环重播/回退兜底（loop 不触发 seeked）
            vdmLastNow = now;
            if (v.paused) return;
            while (vdmCursor < vdmList.length && vdmList[vdmCursor].time <= now + 0.03) {
                const dm = vdmList[vdmCursor++];
                if (vdmEnabled) vdmEmit(dm, now, v);
            }
            vdmUpdatePositions(now);
        }

        function vdmEmit(dm, now, v) {
            const layer = document.getElementById('danmakuLayer');
            if (!layer) return;
            const el = document.createElement('div');
            el.className = 'dm-item' + (dm.mode === 5 ? ' dm-top' : dm.mode === 4 ? ' dm-bottom' : '');
            el.textContent = dm.text;
            el.style.color = dm.color || '#fff';
            el.style.opacity = vdmSettings.opacity;
            layer.appendChild(el);
            const rate = v.playbackRate || 1;
            const stageW = layer.clientWidth;
            const laneCount = Math.max(1, Math.floor(layer.clientHeight / VM_LANE_H));

            if (dm.mode === 1) {
                const dur = Math.max(2, vdmSettings.speed / rate);
                const w = el.offsetWidth;
                if (vdmScrollLanes.length !== laneCount) vdmScrollLanes.length = laneCount;
                let lane = -1;
                for (let i = 0; i < laneCount; i++) {
                    const L = vdmScrollLanes[i];
                    if (!L) { lane = i; break; }
                    const lv = (stageW + L.w) / L.dur;                       // 前弹幕水平速度
                    if ((now - L.start) * lv >= L.w + 12) { lane = i; break; } // 前弹幕尾部已进入屏幕
                }
                if (lane < 0) { el.remove(); return; }                       // 轨道满，丢弃（B站策略）
                vdmScrollLanes[lane] = { start: now, w, dur };
                el.style.top = (lane * VM_LANE_H + 4) + 'px';
                el.style.transform = 'translateX(' + stageW + 'px)';
                vdmActive.push({ el, mode: 1, start: now, dur, w, stageW });
            } else {
                if (vdmFixLanes.length !== laneCount) vdmFixLanes.length = laneCount;
                let lane = -1;
                for (let i = 0; i < laneCount; i++) {
                    if (!vdmFixLanes[i] || vdmFixLanes[i] <= now) { lane = i; break; }
                }
                if (lane < 0) { el.remove(); return; }
                vdmFixLanes[lane] = now + VM_FIX_DUR / rate;
                el.style.top = (dm.mode === 5 ? lane * VM_LANE_H + 4 : layer.clientHeight - (lane + 1) * VM_LANE_H + 6) + 'px';
                vdmActive.push({ el, mode: dm.mode, end: now + VM_FIX_DUR / rate });
            }
        }

        function vdmUpdatePositions(now) {
            for (let i = vdmActive.length - 1; i >= 0; i--) {
                const it = vdmActive[i];
                if (it.mode === 1) {
                    const p = (now - it.start) / it.dur;
                    if (p >= 1) { it.el.remove(); vdmActive.splice(i, 1); continue; }
                    it.el.style.transform = 'translateX(' + (it.stageW - p * (it.stageW + it.w)) + 'px)';
                } else if (now >= it.end) {
                    it.el.remove(); vdmActive.splice(i, 1);
                }
            }
        }

        function vdmInitUI() {
            const v = document.getElementById('videoPlayerEl');
            const input = document.getElementById('dmInput');
            const sendBtn = document.getElementById('dmSendBtn');
            const settingBtn = document.getElementById('dmSettingBtn');
            const panel = document.getElementById('dmSettingPanel');
            const manageBox = document.getElementById('dmManageList');

            // 开关（记忆状态）
            const vdmBtn = document.getElementById('videoDmBtn');
            vdmBtn.classList.toggle('vc-dm-on', vdmEnabled);
            vdmBtn.addEventListener('click', () => {
                vdmEnabled = !vdmEnabled;
                localStorage.setItem('vdmEnabled', vdmEnabled ? '1' : '0');
                vdmBtn.classList.toggle('vc-dm-on', vdmEnabled);
                if (!vdmEnabled) vdmClearActive();
                showToast(vdmEnabled ? '弹幕已开启' : '弹幕已关闭', 'info', 1200);
            });

            // 发送模式
            document.getElementById('dmModeSel').addEventListener('click', (e) => {
                const btn = e.target.closest('.dm-mode-btn');
                if (!btn) return;
                vdmMode = parseInt(btn.dataset.mode);
                document.querySelectorAll('#dmModeSel .dm-mode-btn').forEach(b => b.classList.toggle('active', b === btn));
            });

            // 发送
            sendBtn.addEventListener('click', vdmSend);
            input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); vdmSend(); } });

            // 设置面板显隐
            settingBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const show = panel.style.display === 'none';
                panel.style.display = show ? 'block' : 'none';
                settingBtn.classList.toggle('active', show);
                if (show) vdmRenderManageList();
            });
            document.addEventListener('click', (e) => {
                if (!panel.contains(e.target) && !e.target.closest('#dmSettingBtn')) {
                    panel.style.display = 'none'; settingBtn.classList.remove('active');
                }
            });

            // 设置项
            const opacity = document.getElementById('dmOpacity');
            opacity.value = Math.round(vdmSettings.opacity * 100);
            document.getElementById('dmOpacityVal').textContent = opacity.value + '%';
            opacity.addEventListener('input', () => {
                vdmSettings.opacity = opacity.value / 100;
                document.getElementById('dmOpacityVal').textContent = opacity.value + '%';
                vdmPersistSettings();
                document.querySelectorAll('.dm-item').forEach(el => el.style.opacity = vdmSettings.opacity);
            });
            const area = document.getElementById('dmArea');
            area.value = String(vdmSettings.area);
            area.addEventListener('change', () => { vdmSettings.area = parseFloat(area.value); vdmPersistSettings(); vdmApplyLayerSize(); vdmClearActive(); });
            const speed = document.getElementById('dmSpeed');
            speed.value = String(vdmSettings.speed);
            speed.addEventListener('change', () => { vdmSettings.speed = parseFloat(speed.value); vdmPersistSettings(); });

            // 导入 B站弹幕 XML
            document.getElementById('dmImportBtn').addEventListener('click', () => document.getElementById('dmImportFile').click());
            document.getElementById('dmImportFile').addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (file) vdmImport(file);
                e.target.value = '';
            });

            // 弹幕管理删除（事件委托）
            manageBox.addEventListener('click', (e) => {
                const btn = e.target.closest('.dm-manage-del');
                if (!btn || !videoCurrentId) return;
                const dmId = btn.dataset.dmid;
                fetch('/api/danmaku/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ id: videoCurrentId, dmId }) })
                    .then(r => r.json()).then(j => {
                        if (j.success) {
                            vdmList = vdmList.filter(d => d.id !== dmId);
                            vdmSyncCursor();
                            vdmRenderManageList();
                            showToast('弹幕已删除', 'success', 1000);
                        }
                    }).catch(() => showToast('删除失败', 'error'));
            });

            // seek 后清屏 + 重对齐发射游标
            v.addEventListener('seeked', () => { vdmClearActive(); vdmSyncCursor(); });
        }

        function vdmSend() {
            const input = document.getElementById('dmInput');
            const text = input.value.trim();
            const v = document.getElementById('videoPlayerEl');
            if (!text || !videoCurrentId) return;
            const sendBtn = document.getElementById('dmSendBtn');
            sendBtn.disabled = true;
            fetch('/api/danmaku/add', { method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({ id: videoCurrentId, time: v.currentTime, text, mode: vdmMode, color: document.getElementById('dmColor').value }) })
                .then(r => r.json()).then(j => {
                    if (j.success) {
                        vdmList.push(j.data);
                        vdmList.sort((a, b) => a.time - b.time);
                        vdmSyncCursor();
                        if (vdmEnabled) vdmEmit(j.data, v.currentTime, v); // 自己的弹幕立即上屏
                        input.value = '';
                        vdmRenderManageList();
                    } else showToast(j.error || '弹幕发送失败', 'error');
                }).catch(() => showToast('弹幕发送失败', 'error'))
                .finally(() => sendBtn.disabled = false);
        }

        function vdmImport(file) {
            if (!videoCurrentId) return;
            showToast('正在导入弹幕…', 'info', 1500);
            const fd = new FormData();
            fd.append('id', videoCurrentId);
            fd.append('file', file);
            fetch('/api/danmaku/import', { method:'POST', body: fd })
                .then(r => r.json()).then(j => {
                    if (j.success) {
                        showToast(`导入 ${j.imported} 条弹幕` + (j.skipped ? `，跳过重复 ${j.skipped} 条` : ''), 'success');
                        vdmReload();
                    } else showToast(j.error || '导入失败', 'error');
                }).catch(() => showToast('导入失败', 'error'));
        }

        function vdmEscape(s) {
            return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function vdmRenderManageList() {
            const box = document.getElementById('dmManageList');
            if (!box) return;
            document.getElementById('dmManageCount').textContent = vdmList.length ? `(${vdmList.length})` : '';
            if (!vdmList.length) {
                box.innerHTML = '<div class="dm-manage-empty">还没有弹幕，发一条或导入 B站 XML</div>';
                return;
            }
            box.innerHTML = vdmList.map(d => `
                <div class="dm-manage-item">
                    <span class="dm-manage-time">${videoPadTime(d.time)}</span>
                    <span class="dm-manage-text" ${d.color && d.color.toLowerCase() !== '#ffffff' ? `style="color:${vdmEscape(d.color)}"` : ''}>${vdmEscape(d.text)}</span>
                    <button class="dm-manage-del" data-dmid="${d.id}" title="删除">×</button>
                </div>`).join('');
        }

        function videoFmtTime(sec) {
            if (!sec || !isFinite(sec)) return '';
            const h = Math.floor(sec / 3600);
            const m = Math.floor((sec % 3600) / 60);
            const s = Math.floor(sec % 60);
            if (h > 0) return h + ':' + (m<10?'0':'') + m + ':' + (s<10?'0':'') + s;
            return m + ':' + (s<10?'0':'') + s;
        }
        function videoFmtSize(bytes) {
            if (!bytes) return '-';
            if (bytes < 1024) return bytes + 'B';
            if (bytes < 1048576) return (bytes/1024).toFixed(1) + 'KB';
            if (bytes < 1073741824) return (bytes/1048576).toFixed(1) + 'MB';
            return (bytes/1073741824).toFixed(2) + 'GB';
        }

