(function() {
    // --- DOM 元素 ---
    const overlay = document.getElementById('roomOverlay');
    const usernameInput = document.getElementById('usernameInput');
    const enterBtn = document.getElementById('enterLiveBtn');
    const errorDiv = document.getElementById('nameError');
    const danmakuList = document.getElementById('danmakuList');
    const danmakuInput = document.getElementById('danmakuInput');
    const sendBtn = document.getElementById('sendDanmakuBtn');
    const canvas = document.getElementById('live2d-canvas');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // --- 全局变量 ---
    window.currentUsername = '';
    let ws = null;
    let reconnectTimer = null;
    const WS_URL = 'wss://api.rrrosmontis.icu/v1/live/8000';
    let modelLoadStarted = false;
    let live2dModel = null;
    let modelReady = false;
    let pendingActions = [];
    let startTime = 0;
    let timeDiff = 0;
    let currentSpeechTimer = null;
    let typewriterRAF = null;
    let fadeTimer = null;
    let fadeOutTimer = null;
    let subtitleElement = null;
    let pixiApp = null;                // 保存 PIXI.Application 实例，用于重新加载时销毁

    // --- 平滑嘴型动画相关变量 ---
    let mouthCurrent = 0;
    let mouthTarget = 0;
    let mouthAnimationFrame = null;
    let mouthInterval = null;

    // --- 进度条相关变量 ---
    let modelLoaded = false;
    let wsConnected = false;
    let progressCompleted = false;
    let progressFill = null;
    let progressWrapper = null;
    let hideProgressTimer = null;

    // --- 冷却状态标志 ---
    let isCooldown = false;

    // --- 模型原始尺寸（用于位置调整）---
    let originalModelWidth = 0;
    let originalModelHeight = 0;

    // --- 工具函数 ---
    function isValidUsername(name) {
        if (!name || name.length === 0 || name.length > 20) return false;
        return /^[a-zA-Z0-9_-]{1,20}$/.test(name);
    }

    function getAvatarColor(user) {
        const colors = ['#5dade2', '#f1c40f', '#9b59b6', '#e67e22', '#2ecc71', '#e84342'];
        let hash = 0;
        for (let i = 0; i < user.length; i++) hash = user.charCodeAt(i) + ((hash << 5) - hash);
        return colors[Math.abs(hash) % colors.length];
    }

    function addDanmakuItem(text, user, time) {
        const emptyDivs = danmakuList.querySelectorAll('.danmaku-empty');
        emptyDivs.forEach(el => el.remove());
        const item = document.createElement('div');
        item.className = 'danmaku-item';
        const avatar = document.createElement('div');
        avatar.className = 'danmaku-avatar';
        avatar.style.backgroundColor = getAvatarColor(user);
        const content = document.createElement('div');
        content.className = 'danmaku-content';
        const userSpan = document.createElement('span');
        userSpan.className = 'danmaku-user';
        userSpan.textContent = user;
        const textSpan = document.createElement('span');
        textSpan.className = 'danmaku-text';
        textSpan.textContent = text;
        content.appendChild(userSpan);
        content.appendChild(textSpan);
        item.appendChild(avatar);
        item.appendChild(content);
        danmakuList.appendChild(item);
        danmakuList.scrollTop = danmakuList.scrollHeight;
    }

    function showEmptyDanmaku() {
        danmakuList.innerHTML = '<div class="danmaku-empty">还没有弹幕呢</div>';
    }

    // --- 创建台词显示元素 ---
    function createSubtitleElement() {
        const wrapper = document.querySelector('.video-wrapper');
        if (!wrapper) return;
        subtitleElement = document.createElement('div');
        subtitleElement.id = 'subtitle';
        subtitleElement.style.position = 'absolute';
        subtitleElement.style.bottom = '15%';
        subtitleElement.style.left = '50%';
        subtitleElement.style.transform = 'translateX(-50%)';
        subtitleElement.style.backgroundColor = 'transparent';
        subtitleElement.style.color = '#fff';
        subtitleElement.style.padding = '8px 20px';
        subtitleElement.style.borderRadius = '30px';
        subtitleElement.style.fontSize = '1.2rem';
        subtitleElement.style.fontFamily = 'Kazesawa-Regular, sans-serif';
        subtitleElement.style.textAlign = 'center';
        subtitleElement.style.maxWidth = '80%';
        subtitleElement.style.wordBreak = 'break-word';
        subtitleElement.style.boxShadow = 'none';
        subtitleElement.style.textShadow = '0 0 10px #fff, 0 0 20px #fff, 0 0 30px #00aaff';
        subtitleElement.style.zIndex = '100';
        subtitleElement.style.display = 'none';
        subtitleElement.style.opacity = '1';
        subtitleElement.style.transition = 'opacity 1s ease';
        wrapper.appendChild(subtitleElement);
    }

    // --- 统一更新输入控件状态 ---
    function updateInputState() {
        const enabled = ws && ws.readyState === WebSocket.OPEN && window.currentUsername && !isCooldown;
        danmakuInput.disabled = !enabled;
        sendBtn.disabled = !enabled;
    }

    // --- 开始说话（包含嘴型动画和字幕）---
    function startSpeaking(text) {
        if (!live2dModel) {
            console.warn('[SPEAK] 模型未就绪，无法说话');
            return;
        }

        console.log(`[SPEAK] 开始说话，文本: "${text}"`);
        stopSpeaking();

        if (subtitleElement) {
            subtitleElement.style.display = 'block';
            subtitleElement.style.opacity = '1';
            subtitleElement.innerHTML = '';
        }

        const duration = Math.max(1, text.length * 0.2);
        const totalDurationMs = duration * 1000;
        const len = text.length;
        console.log(`[SPEAK] 预计说话时长: ${duration}s, 总字符: ${len}`);

        // 逐字追加字符
        if (len > 0) {
            const typewriterStartTime = Date.now();
            let lastCharCount = 0;

            function typewriter() {
                const elapsed = Date.now() - typewriterStartTime;
                let charsToShow = Math.floor(elapsed / totalDurationMs * len);
                if (charsToShow > len) charsToShow = len;

                if (charsToShow > lastCharCount) {
                    for (let i = lastCharCount; i < charsToShow; i++) {
                        const char = text[i];
                        const span = document.createElement('span');
                        span.className = 'subtitle-char';
                        span.textContent = char;
                        subtitleElement.appendChild(span);
                    }
                    lastCharCount = charsToShow;
                }

                if (charsToShow < len) {
                    typewriterRAF = requestAnimationFrame(typewriter);
                } else {
                    typewriterRAF = null;
                    if (subtitleElement) {
                        if (fadeTimer) clearTimeout(fadeTimer);
                        if (fadeOutTimer) clearTimeout(fadeOutTimer);
                        fadeTimer = setTimeout(() => {
                            console.log('[SPEAK] 字幕显示完毕，开始渐隐');
                            subtitleElement.style.opacity = '0';
                            fadeOutTimer = setTimeout(() => {
                                if (subtitleElement) {
                                    subtitleElement.style.display = 'none';
                                    subtitleElement.style.opacity = '1';
                                    subtitleElement.innerHTML = '';
                                }
                                fadeOutTimer = null;
                            }, 1000);
                            fadeTimer = null;
                        }, 1000);
                    }
                }
            }
            typewriterRAF = requestAnimationFrame(typewriter);
        }

        // 嘴型平滑动画
        mouthCurrent = 0;
        mouthTarget = 0;
        let pauseFrames = 0;

        mouthInterval = setInterval(() => {
            if (!live2dModel) return;

            if (pauseFrames > 0) {
                mouthTarget = 0;
                pauseFrames--;
            } else {
                const target = 0.2 + Math.random() * 0.6;
                mouthTarget = target;

                if (Math.random() < 0.2) {
                    pauseFrames = Math.floor(Math.random() * 4) + 2;
                }
            }
        }, 100);

        function animateMouth() {
            if (!live2dModel) {
                if (mouthAnimationFrame) {
                    cancelAnimationFrame(mouthAnimationFrame);
                    mouthAnimationFrame = null;
                }
                return;
            }

            const diff = mouthTarget - mouthCurrent;
            const step = diff * 0.3;
            mouthCurrent += step;

            if (Math.abs(diff) < 0.01) {
                mouthCurrent = mouthTarget;
            }

            try {
                live2dModel.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouthCurrent, 1.0);
            } catch (e) {
                console.warn('[SPEAK] 设置嘴部参数失败', e);
            }

            mouthAnimationFrame = requestAnimationFrame(animateMouth);
        }
        mouthAnimationFrame = requestAnimationFrame(animateMouth);

        // 说话结束定时器
        currentSpeechTimer = setTimeout(() => {
            console.log('[SPEAK] 说话时间结束，停止生成新目标');
            if (mouthInterval) {
                clearInterval(mouthInterval);
                mouthInterval = null;
            }
            mouthTarget = 0;
        }, totalDurationMs);
    }

    function stopSpeaking() {
        if (mouthInterval) {
            clearInterval(mouthInterval);
            mouthInterval = null;
        }
        if (mouthAnimationFrame) {
            cancelAnimationFrame(mouthAnimationFrame);
            mouthAnimationFrame = null;
        }
        mouthCurrent = 0;
        mouthTarget = 0;

        if (currentSpeechTimer) {
            clearTimeout(currentSpeechTimer);
            currentSpeechTimer = null;
        }
        if (typewriterRAF) {
            cancelAnimationFrame(typewriterRAF);
            typewriterRAF = null;
        }
        if (fadeTimer) {
            clearTimeout(fadeTimer);
            fadeTimer = null;
        }
        if (fadeOutTimer) {
            clearTimeout(fadeOutTimer);
            fadeOutTimer = null;
        }
        if (subtitleElement) {
            subtitleElement.style.display = 'none';
            subtitleElement.style.opacity = '1';
            subtitleElement.innerHTML = '';
        }
        if (live2dModel) {
            try {
                live2dModel.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', 0, 1.0);
                console.log('[SPEAK] 强制重置嘴部为闭合');
            } catch (e) {
                console.warn('[SPEAK] 重置嘴部失败', e);
            }
        }
    }

    // --- 执行动作 ---
    function playAction(actionObj) {
        if (!live2dModel) {
            console.warn('[ACTION] 模型未就绪，无法执行动作');
            return;
        }
        const { type, motion, params } = actionObj;
        if (type === 1) {
            if (motion) {
                try {
                    live2dModel.motion(motion, 0, 3);
                    console.log(`[ACTION] 播放动作: ${motion}`);
                } catch (e) {
                    console.error('[ACTION] 播放动作失败', e);
                }
            }
        } else if (type === 0) {
            if (params) {
                if (typeof params === 'object' && params !== null) {
                    for (let [param, value] of Object.entries(params)) {
                        try {
                            live2dModel.internalModel.coreModel.setParameterValueById(param, value, 1.0);
                            console.log(`[ACTION] 设置参数 ${param} = ${value}`);
                        } catch (e) {
                            console.warn(`[ACTION] 设置参数 ${param} 失败`, e);
                        }
                    }
                    live2dModel.update();
                }
            }
        }
    }

    // --- 调度动作 (基于时间同步) ---
    function scheduleAction(actionData) {
        const { time, action, text } = actionData;
        const targetServerTime = startTime + time;
        const targetLocalTime = targetServerTime + timeDiff;
        const nowLocal = Date.now() / 1000;
        let delayMs = (targetLocalTime - nowLocal) * 1000;
        if (delayMs < 0) delayMs = 0;
        console.log(`[SCHEDULE] 动作将在 ${delayMs}ms 后执行，文本: ${text || '无'}`);
        setTimeout(() => {
            if (!modelReady) {
                console.log('[SCHEDULE] 模型未就绪，暂存动作');
                pendingActions.push({ action, text });
            } else {
                playAction(action);
                if (text) startSpeaking(text);
            }
        }, delayMs);
    }

    // --- 模型就绪处理 ---
    function onModelReady() {
        modelReady = true;
        console.log('[MODEL] 模型已就绪，执行暂存动作数量:', pendingActions.length);
        pendingActions.forEach(item => {
            playAction(item.action);
            if (item.text) startSpeaking(item.text);
        });
        pendingActions = [];
    }

    // --- 手动测试函数 (保持不变) ---
    window.live2dTest = {
        motions: function() { 
            if (live2dModel && live2dModel.internalModel && live2dModel.internalModel.motionManager) {
                const motions = Object.keys(live2dModel.internalModel.motionManager._motionGroups || {});
                console.log('[TEST] 可用动作组:', motions);
            } else {
                console.warn('[TEST] 模型未就绪');
            }
        },
        expressions: function() { 
            if (live2dModel && live2dModel.internalModel && live2dModel.internalModel.expressionManager) {
                const exps = Object.keys(live2dModel.internalModel.expressionManager._expressions || {});
                console.log('[TEST] 可用表情:', exps);
            } else {
                console.warn('[TEST] 模型未就绪');
            }
        },
        play: function(motionName) { 
            if (live2dModel) {
                live2dModel.motion(motionName);
                console.log(`[TEST] 手动播放动作: ${motionName}`);
            }
        },
        speak: function(text) { 
            console.log(`[TEST] 手动调用说话: ${text}`);
            startSpeaking(text); 
        },
        params: function() {
            if (live2dModel && live2dModel.internalModel && live2dModel.internalModel.coreModel) {
                const params = live2dModel.internalModel.coreModel._parameters;
                if (params && params.length) {
                    console.log('[TEST] 模型参数列表:');
                    for (let i = 0; i < params.length; i++) {
                        console.log(`  ${i}: ${params[i].id} = ${params[i].value}`);
                    }
                } else {
                    console.log('[TEST] 模型参数列表为空或不可用');
                }
            }
        }
    };

    // --- 进度条更新函数 ---
    function updateProgress() {
        let progress = 10;
        if (modelLoaded) progress += 70;
        if (wsConnected) progress += 30;
        if (progress > 100) progress = 100;

        if (progressFill) {
            progressFill.style.width = progress + '%';
        }

        if (progress >= 100 && !progressCompleted) {
            progressCompleted = true;
            if (enterBtn) enterBtn.disabled = false;
            if (hideProgressTimer) clearTimeout(hideProgressTimer);
            hideProgressTimer = setTimeout(() => {
                if (progressWrapper) {
                    progressWrapper.style.opacity = '0';
                    setTimeout(() => {
                        if (progressWrapper) {
                            progressWrapper.style.display = 'none';
                        }
                    }, 1000);
                }
                hideProgressTimer = null;
            }, 1000);
        } else if (progress < 100) {
            if (enterBtn) enterBtn.disabled = true;
        }
    }

    // --- WebSocket 连接 ---
    function connectWebSocket() {
        if (ws && ws.readyState === WebSocket.OPEN) return;
        ws = new WebSocket(WS_URL);

        ws.onopen = () => { 
            console.log('[WS] 已连接');
            wsConnected = true;
            updateProgress();
            updateInputState();   // 更新输入状态
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            } catch (e) { console.error('[WS] 消息解析失败', e); }
        };

        ws.onerror = (err) => { console.error('[WS] 错误', err); };

        ws.onclose = () => {
            console.log('[WS] 关闭，尝试重连...');
            danmakuList.innerHTML = '';
            showEmptyDanmaku();
            updateInputState();   // ws 关闭，输入自动禁用
            if (reconnectTimer) clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectWebSocket, 3000);
        };
    }

    function handleMessage(msg) {
        console.log('[WS] 收到消息:', msg);
        switch (msg.type) {
            case 'init':
                startTime = msg.start_time;
                const serverNow = startTime + msg.elapsed;
                const localNow = Date.now() / 1000;
                timeDiff = localNow - serverNow;
                console.log(`[INIT] 时间同步: timeDiff = ${timeDiff}s`);

                danmakuList.innerHTML = '';
                if (msg.recent_danmaku && msg.recent_danmaku.length > 0) {
                    msg.recent_danmaku.forEach(d => {
                        addDanmakuItem(d.text, d.user, d.time);
                    });
                } else {
                    showEmptyDanmaku();
                }

                if (msg.recent_actions && msg.recent_actions.length > 0) {
                    console.log(`[INIT] 收到 ${msg.recent_actions.length} 个历史动作`);
                    msg.recent_actions.forEach(actionData => {
                        scheduleAction(actionData);
                    });
                }

                updateInputState();   // 根据用户名和 ws 状态更新输入
                break;

            case 'danmaku':
                if (msg.data) addDanmakuItem(msg.data.text, msg.data.user, msg.data.time);
                break;

            case 'action':
                console.log('[ACTION] 收到动作消息:', msg.data);
                if (msg.data) scheduleAction(msg.data);
                break;

            default: console.log('[WS] 未处理消息类型', msg.type);
        }
    }

    function sendDanmaku() {
        if (!ws || ws.readyState !== WebSocket.OPEN) { 
            alert('连接未建立，请稍后');   // 保留连接失败提示（或可改为UI提示）
            return; 
        }
        if (isCooldown) return;   // 冷却中直接返回

        const text = danmakuInput.value.trim();
        if (text === '') return;

        const payload = { type: 'danmaku', text: text, user: window.currentUsername || '匿名' };
        ws.send(JSON.stringify(payload));
        danmakuInput.value = '';

        // 进入冷却
        isCooldown = true;
        updateInputState();

        // 5秒后解除冷却
        setTimeout(() => {
            isCooldown = false;
            updateInputState();
        }, 5000);

        console.log('[SEND] 发送弹幕:', payload);
    }

    // --- Live2D 模型位置调整函数（使用 getBoundingClientRect 获取实际尺寸，兼容旋转布局）---
    function adjustModelPosition() {
        const model = live2dModel;
        const app = pixiApp;
        if (!model || !app || !canvas) return;

        // 使用 getBoundingClientRect 获取实际渲染尺寸（考虑 CSS 变换）
        const canvasRect = canvas.getBoundingClientRect();
        const canvasWidth = canvasRect.width;
        const canvasHeight = canvasRect.height;

        if (canvasWidth === 0 || canvasHeight === 0) {
            console.warn('[MODEL] Canvas尺寸为0，延迟调整');
            setTimeout(adjustModelPosition, 100);
            return;
        }

        if (originalModelWidth === 0 || originalModelHeight === 0) {
            console.warn('[MODEL] 原始模型尺寸为0，延迟调整');
            setTimeout(adjustModelPosition, 100);
            return;
        }

        // 确保渲染器尺寸与 canvas 实际像素尺寸一致
        if (app.renderer) {
            app.renderer.resize(canvasWidth, canvasHeight);
        }

        const scale = (canvasHeight * 3.0) / originalModelHeight;
        model.scale.set(scale);
        const scaledWidth = originalModelWidth * scale;
        const x = (canvasWidth - scaledWidth) / 2;
        const y = canvasHeight * 0.005;
        model.position.set(x, y);

        // 强制重绘一次（Safari 有时需要）
        app.renderer.render(app.stage);
        console.log('[MODEL] 调整位置完成，scale=' + scale);
    }

    // --- Live2D 模型加载 ---
    async function loadLive2DModel() {
        // 显示加载遮罩
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        if (!canvas) {
            console.error('[MODEL] Canvas元素不存在');
            return;
        }
        if (typeof PIXI === 'undefined' || !PIXI.live2d) {
            console.error('[MODEL] Live2D库未正确加载');
            // 改为在加载遮罩上显示错误，不绘制黑色背景
            if (loadingOverlay) {
                loadingOverlay.textContent = 'Live2D库加载失败，请刷新';
                loadingOverlay.style.display = 'flex';
            }
            modelLoaded = true;
            updateProgress();
            return;
        }

        const modelUrl = 'https://cdn.rrrosmontis.icu/tsukuyomi/8000/八千代辉夜姬.model3.json';

        // 清理旧应用
        if (pixiApp) {
            try {
                pixiApp.destroy(true);
            } catch (e) {
                console.warn('[MODEL] 销毁旧应用失败', e);
            }
            pixiApp = null;
            live2dModel = null;
            modelReady = false;
            modelLoaded = false;
            originalModelWidth = 0;
            originalModelHeight = 0;
        }

        // 增强 PIXI 配置，针对 Safari 添加 preserveDrawingBuffer
        const app = new PIXI.Application({
            view: canvas,
            transparent: true,
            preserveDrawingBuffer: true,   // 解决 Safari 透明问题
            backgroundColor: 0x000000,     // 透明模式下无效，但保留
            clearBeforeRender: true,
            width: canvas.clientWidth,
            height: canvas.clientHeight,
            resizeTo: canvas,
            antialias: true,
            powerPreference: 'high-performance'
        });
        pixiApp = app;

        try {
            console.log('[MODEL] 开始加载模型:', modelUrl);
            const model = await PIXI.live2d.Live2DModel.from(modelUrl, { autoInteract: false });
            app.stage.addChild(model);

            live2dModel = model;
            window.live2dModel = model;

            // 保存原始尺寸（此时 scale = 1）
            originalModelWidth = model.width;
            originalModelHeight = model.height;
            console.log(`[MODEL] 原始尺寸: ${originalModelWidth} x ${originalModelHeight}`);

            // 延迟一点再调整位置，确保布局稳定（尤其旋转后）
            setTimeout(adjustModelPosition, 200);

            // 监听模型加载完成事件（某些模型可能异步加载内部资源）
            model.on('load', adjustModelPosition);

            // 监听窗口大小变化和屏幕旋转
            window.addEventListener('resize', adjustModelPosition);
            window.addEventListener('orientationchange', adjustModelPosition);

            // 打印可用动作和表情（延迟确保 internalModel 就绪）
            setTimeout(() => {
                if (model.internalModel) {
                    if (model.internalModel.motionManager) {
                        const motions = Object.keys(model.internalModel.motionManager._motionGroups || {});
                        console.log('[MODEL] 可用动作组:', motions);
                    }
                    if (model.internalModel.expressionManager) {
                        const exps = Object.keys(model.internalModel.expressionManager._expressions || {});
                        console.log('[MODEL] 可用表情:', exps);
                    }
                }
            }, 500);

            modelLoaded = true;
            updateProgress();
            onModelReady();

            console.log('[MODEL] 模型加载成功');
            if (loadingOverlay) loadingOverlay.style.display = 'none';
        } catch (error) {
            console.error('[MODEL] 模型加载失败:', error);
            // 在加载遮罩上显示错误，不绘制黑色背景
            if (loadingOverlay) {
                loadingOverlay.textContent = '模型加载失败，请刷新重试';
                loadingOverlay.style.display = 'flex';
            }
            modelLoaded = true;
            updateProgress();
        }
    }

    // --- 渐隐遮罩层 ---
    function fadeOutOverlay() {
        if (!overlay) return;
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.style.display = 'none';
            overlay.classList.remove('fade-out');
            // 遮罩完全隐藏后，重新调整模型位置
            adjustModelPosition();
        }, 3000); // 与CSS过渡时间一致
    }

    // --- 用户名确认处理 (包含重新加载模型) ---
    function handleEnter() {
        const rawName = usernameInput.value.trim();
        if (rawName === '') { errorDiv.innerText = '用户名不能为空'; return; }
        if (!isValidUsername(rawName)) { errorDiv.innerText = '用户名需为1-20位，只能包含字母、数字、下划线(_)或连字符(-)'; return; }

        window.currentUsername = rawName;
        console.log('[ENTER] 用户登录:', window.currentUsername);

        fadeOutOverlay();
        updateInputState();   // 用户名已设置，更新输入状态
    }

    // --- 事件绑定 ---
    enterBtn.addEventListener('click', (e) => { e.preventDefault(); handleEnter(); });
    usernameInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); handleEnter(); } });
    sendBtn.addEventListener('click', (e) => { e.preventDefault(); sendDanmaku(); });
    danmakuInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendDanmaku(); } });

    // --- 初始化 ---
    showEmptyDanmaku();
    createSubtitleElement();

    window.addEventListener('load', function() {
        console.log('[INIT] 页面加载完成');
        progressFill = document.getElementById('progressFill');
        progressWrapper = document.getElementById('progressWrapper');
        updateProgress();

        loadLive2DModel();   // 初次加载模型
        connectWebSocket();
    });
})();