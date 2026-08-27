#!/usr/bin/env node
/* Run the standalone preview Diagnostics Runner in headless Chromium without app servers. */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { spawn } = require('child_process');

function parseArgs(argv) {
  const result = { input: null, output: null, screenshot: null, geometryOutput: null, captureView: null, captureScreen: null, captureLeftPanel: null, captureRightPanel: null, captureInspectorTab: null, captureReviewSection: null, viewportWidth: 1440, viewportHeight: 960, failOnFindings: false, timeoutMs: 60000 };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--output') result.output = argv[++index];
    else if (value === '--screenshot') result.screenshot = argv[++index];
    else if (value === '--geometry-output') result.geometryOutput = argv[++index];
    else if (value === '--capture-view') result.captureView = argv[++index];
    else if (value === '--capture-screen') result.captureScreen = argv[++index];
    else if (value === '--capture-left-panel') result.captureLeftPanel = argv[++index];
    else if (value === '--capture-right-panel') result.captureRightPanel = argv[++index];
    else if (value === '--capture-inspector-tab') result.captureInspectorTab = argv[++index];
    else if (value === '--capture-review-section') result.captureReviewSection = argv[++index];
    else if (value === '--viewport-width') result.viewportWidth = Number(argv[++index]);
    else if (value === '--viewport-height') result.viewportHeight = Number(argv[++index]);
    else if (value === '--fail-on-findings') result.failOnFindings = true;
    else if (value === '--timeout-ms') result.timeoutMs = Number(argv[++index]);
    else if (!result.input) result.input = value;
    else throw new Error(`Unexpected argument: ${value}`);
  }
  if (!result.input) throw new Error('Usage: smoke_preview.js <ui-preview.html> [--output diagnostics.json] [--screenshot preview.png] [--geometry-output geometry.json] [--capture-view overview|prototype|single|states|compare] [--capture-screen ID] [--capture-left-panel open|closed] [--capture-right-panel open|closed] [--capture-inspector-tab inspect|review|comments] [--capture-review-section summary|problems|changes] [--viewport-width 1440] [--viewport-height 960] [--fail-on-findings]');
  if (result.captureView && !['overview', 'prototype', 'single', 'states', 'compare'].includes(result.captureView)) throw new Error('--capture-view must be overview, prototype, single, states, or compare');
  if (result.captureLeftPanel && !['open', 'closed'].includes(result.captureLeftPanel)) throw new Error('--capture-left-panel must be open or closed');
  if (result.captureRightPanel && !['open', 'closed'].includes(result.captureRightPanel)) throw new Error('--capture-right-panel must be open or closed');
  if (result.captureInspectorTab && !['inspect', 'review', 'comments'].includes(result.captureInspectorTab)) throw new Error('--capture-inspector-tab must be inspect, review, or comments');
  if (result.captureReviewSection && !['summary', 'problems', 'changes'].includes(result.captureReviewSection)) throw new Error('--capture-review-section must be summary, problems, or changes');
  if (!Number.isFinite(result.viewportWidth) || result.viewportWidth < 320 || !Number.isFinite(result.viewportHeight) || result.viewportHeight < 320) throw new Error('Viewport width and height must be at least 320');
  return result;
}

function chromeCandidates() {
  const values = [process.env.CHROME_PATH];
  if (process.platform === 'win32') {
    values.push(
      'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    );
  } else if (process.platform === 'darwin') {
    values.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge');
  } else {
    values.push('/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge');
  }
  return values.filter(Boolean);
}

function findChrome() {
  const executable = chromeCandidates().find(candidate => fs.existsSync(candidate));
  if (!executable) throw new Error('Chromium browser not found. Set CHROME_PATH to Chrome, Edge, or Chromium.');
  return executable;
}

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitForFile(file, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(file) && fs.statSync(file).size > 0) return;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${file}`);
}

async function connectCdp(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', () => reject(new Error('Cannot connect to Chromium DevTools')), { once: true });
  });
  let nextId = 1;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const payload = JSON.parse(String(event.data));
    if (!payload.id || !pending.has(payload.id)) return;
    const { resolve, reject } = pending.get(payload.id);
    pending.delete(payload.id);
    if (payload.error) reject(new Error(payload.error.message));
    else resolve(payload.result);
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  return { socket, call };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const input = path.resolve(args.input);
  if (!fs.existsSync(input)) throw new Error(`Preview not found: ${input}`);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ui-design-workbench-smoke-'));
  const activePort = path.join(profile, 'DevToolsActivePort');
  const url = pathToFileURL(input);
  url.searchParams.set('diagnostics', 'run');
  url.searchParams.set('lang', 'ru');
  const browser = spawn(findChrome(), [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--disable-background-networking',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    url.href,
  ], { stdio: 'ignore', windowsHide: true });
  let socket;
  try {
    await waitForFile(activePort, Math.min(args.timeoutMs, 15000));
    const [port] = fs.readFileSync(activePort, 'utf8').trim().split(/\r?\n/);
    let targets = [];
    const targetDeadline = Date.now() + 15000;
    while (Date.now() < targetDeadline) {
      targets = await fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json());
      if (targets.some(target => target.type === 'page' && target.url.startsWith('file:'))) break;
      await delay(100);
    }
    const target = targets.find(item => item.type === 'page' && item.url.startsWith('file:'));
    if (!target) throw new Error('Preview page was not created by Chromium');
    const cdp = await connectCdp(target.webSocketDebuggerUrl);
    socket = cdp.socket;
    await cdp.call('Runtime.enable');
    await cdp.call('Emulation.setDeviceMetricsOverride', { width: args.viewportWidth, height: args.viewportHeight, deviceScaleFactor: 1, mobile: false });
    const deadline = Date.now() + args.timeoutMs;
    let status = 'idle';
    while (Date.now() < deadline) {
      const response = await cdp.call('Runtime.evaluate', { expression: "document.documentElement.dataset.diagnosticsStatus || 'idle'", returnByValue: true });
      status = response.result?.value || 'idle';
      if (status === 'complete') break;
      await delay(200);
    }
    if (status !== 'complete') throw new Error(`Diagnostics did not finish within ${args.timeoutMs}ms (status=${status})`);
    const response = await cdp.call('Runtime.evaluate', { expression: "document.getElementById('runtime-diagnostics-report').textContent", returnByValue: true });
    const report = JSON.parse(response.result?.value || 'null');
    if (!report || report.status !== 'complete') throw new Error('Diagnostics report is missing or incomplete');
    const initialVisualStateResponse = await cdp.call('Runtime.evaluate', {
      expression: `({
        view: state.view,
        screen: state.screen,
        activeVersion: state.activeVersion,
        compareBaseVersion: state.compareBaseVersion,
        compareTargetVersion: state.compareTargetVersion,
        versionDecision: state.versionDecision,
        findingDecisions: JSON.parse(JSON.stringify(state.findingDecisions)),
        findingFilter: state.findingFilter,
        findingSource: state.findingSource,
        findingScreen: state.findingScreen,
        findingFocus: JSON.parse(JSON.stringify(state.findingFocus)),
        runtimeFindings: JSON.parse(JSON.stringify(state.runtimeFindings)),
        reviewSection: state.reviewSection,
        reviewScope: state.reviewScope,
        reviewRuns: JSON.parse(JSON.stringify(state.reviewRuns)),
        importedReview: JSON.parse(JSON.stringify(state.importedReview)),
        sidebarOpen: state.sidebarOpen,
        inspectorOpen: state.inspectorOpen,
        inspectorTab: state.inspectorTab,
        zoomMode: state.zoomMode,
        zoom: state.zoom,
        selectedNodeId: state.selectedNodeId,
        selectedScreenId: state.selectedScreenId,
        focusedFindingId: state.focusedFindingId,
        openFindingId: state.openFindingId,
        showFindings: state.showFindings,
        showBefore: state.showBefore,
        showAfter: state.showAfter,
        layerReturnView: state.layerReturnView,
        diagnosticTargetIds: JSON.parse(JSON.stringify(state.diagnosticTargetIds)),
        stageScroll: JSON.parse(JSON.stringify(state.stageScroll)),
        screenScrolls: JSON.parse(JSON.stringify(state.screenScrolls)),
      })`,
      returnByValue: true,
    });
    const initialVisualState = initialVisualStateResponse.result?.value || {};
    const workflowResponse = await cdp.call('Runtime.evaluate', {
      expression: `(async () => {
        const totalBefore = Number(document.querySelector('.finding-total')?.textContent || 0);
        const auditLink = document.querySelector('[data-audit-findings]');
        if (auditLink) auditLink.click();
        const linkedVisible = !document.querySelector('.finding-context')?.hidden;
        document.querySelector('.finding-context button')?.click();
        const diagnosticAction = [...document.querySelectorAll('[data-accept-diagnostic]')]
          .find(button => button.closest('.diagnostic-card')?.dataset.result !== 'pass');
        diagnosticAction?.click();
        await runAutomatedReview();
        const actionableChecks = (state.diagnostics?.checks || []).filter(item => item.result !== 'pass').length;
        const actionableGroups = groupDiagnosticChecks((state.diagnostics?.checks || []).filter(item => item.result !== 'pass')).length;
        const totalAfter = Number(document.querySelector('.finding-total')?.textContent || 0);
        const autoReviewFindings = state.runtimeFindings.length;
        const selected = Number(document.querySelector('.fix-queue-count')?.textContent || 0);
        const request = selected && typeof fixRequestPayload === 'function' ? fixRequestPayload() : null;
        const expertRequest = typeof expertReviewRequestPayload === 'function' ? expertReviewRequestPayload() : null;
        const expertHandoff = window.__uiPreviewDiagnostics?.agentHandoff?.('expert');
        const proposalHandoff = window.__uiPreviewDiagnostics?.agentHandoff?.('proposal');
        state.agentHandoff = {
          kind: 'proposal', status: 'prepared', createdAt: new Date().toISOString(),
          acceptedFindingIds: proposalHandoff?.context?.acceptedFindingIds || [],
          screenIds: proposalHandoff?.context?.screenIds || [], artifactDir: proposalHandoff?.path || ''
        };
        renderAgentHandoff();
        const handoffPanelWorks = document.querySelector('.agent-handoff-panel')?.hidden === false
          && Boolean(document.querySelector('.copy-agent-task'))
          && Boolean(document.querySelector('.refresh-preview'))
          && document.querySelector('.agent-handoff-meta')?.textContent?.includes('выбранном AI-агенте');
        state.agentHandoff = null;
        renderAgentHandoff();
        const runtimeActionable = Boolean(request?.findings?.some(item => item.runtimeDiagnosticId));
        const contextProposalAction = ['proposal', 'compare-selected', 'approve', 'source'].includes(document.querySelector('.review-next-action')?.dataset.action);
        const smokeFinding = {
          id: 'smoke-imported-finding', title: 'Smoke imported finding', category: 'smoke', severity: 'low', confidence: 'high',
          screenId: screens[0].id, observation: 'Imported during smoke.', impact: 'None.', recommendation: 'None.',
          evidence: [{ type: 'source', ref: 'smoke', note: 'Synthetic smoke fixture.' }], effort: 'small', proposalVersionId: 'smoke-imported-proposal'
        };
        importExpertReviewData({
          type: 'ui-design-workbench-expert-review-result', requestRevision: reviewRevision, project: ir.project?.name,
          summary: 'Smoke import', findings: [smokeFinding],
          versions: [{ id: 'smoke-imported-proposal', label: 'Smoke proposal', kind: 'proposal', parent: baselineVersion, findingIds: [smokeFinding.id], resolvedFindingIds: [smokeFinding.id], nodeOverrides: {} }]
        });
        const importWorks = state.importedReview?.addedVersions === 1
          && findings.some(item => item.id === smokeFinding.id)
          && versionById['smoke-imported-proposal'];
        state.compareBaseVersion = versions[1]?.id || baselineVersion;
        state.compareTargetVersion = 'smoke-imported-proposal';
        state.findingFocus = [];
        state.findingFilter = 'all';
        state.findingSource = 'all';
        state.findingScreen = 'all';
        state.showFindings = true;
        const smokeAnnotation = {
          id: 'smoke-canvas-comment', screenId: screens[0].id, nodeId: null,
          versionId: 'smoke-imported-proposal', text: 'Smoke user comment.', priority: 'medium', status: 'new'
        };
        state.annotations.push(smokeAnnotation);
        renderQueue();
        renderCompareVersionOptions();
        setScreen(screens[0].id, 'compare');
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const compareVariantsWork = document.querySelectorAll('.compare-panel').length === 2
          && getComputedStyle(document.querySelector('.header-version-picker')).display === 'none'
          && document.querySelectorAll('.compare-version-select').length === 2
          && getComputedStyle(document.querySelector('.compare-workspace-controls')).display === 'flex';
        const smokeMarker = document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]');
        const smokeCommentMarker = document.querySelector('[data-open-annotation="' + CSS.escape(smokeAnnotation.id) + '"]');
        const baseDeviceRect = document.querySelector('.device[data-version-id="' + CSS.escape(state.compareBaseVersion) + '"]')?.getBoundingClientRect();
        const targetDeviceRect = document.querySelector('.device[data-version-id="' + CSS.escape(state.compareTargetVersion) + '"]')?.getBoundingClientRect();
        const findingMarkerRect = smokeMarker?.getBoundingClientRect();
        const commentMarkerRect = smokeCommentMarker?.getBoundingClientRect();
        const markersFollowComparedViews = Boolean(baseDeviceRect && targetDeviceRect && findingMarkerRect && commentMarkerRect
          && findingMarkerRect.left + findingMarkerRect.width / 2 < baseDeviceRect.left
          && commentMarkerRect.left + commentMarkerRect.width / 2 > targetDeviceRect.right);
        const userCommentHasDistinctColor = Boolean(smokeCommentMarker
          && getComputedStyle(smokeCommentMarker).backgroundColor === 'rgb(124, 58, 237)');
        smokeCommentMarker?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const commentPopoverOpens = Boolean(document.querySelector('[data-annotation-popover="' + CSS.escape(smokeAnnotation.id) + '"]'));
        document.querySelector('[data-collapse-annotation="' + CSS.escape(smokeAnnotation.id) + '"]')?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const commentPopoverCollapses = !document.querySelector('[data-annotation-popover="' + CSS.escape(smokeAnnotation.id) + '"]')
          && Boolean(document.querySelector('[data-open-annotation="' + CSS.escape(smokeAnnotation.id) + '"]'));
        const smokeListNumber = document.querySelector('.finding-card[data-finding-id="' + CSS.escape(smokeFinding.id) + '"] .finding-list-index')?.textContent?.trim();
        const markerNumberMatches = Boolean(smokeMarker && smokeMarker.textContent.trim() === smokeListNumber);
        smokeMarker?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const markerPopoverOpens = Boolean(document.querySelector('[data-finding-popover="' + CSS.escape(smokeFinding.id) + '"]'));
        document.querySelector('[data-collapse-finding="' + CSS.escape(smokeFinding.id) + '"]')?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const markerPopoverCollapses = !document.querySelector('[data-finding-popover="' + CSS.escape(smokeFinding.id) + '"]')
          && Boolean(document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]'));
        const findingsToggle = document.querySelector('[data-canvas-layer="findings"]');
        findingsToggle?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const markersHide = document.querySelectorAll('.finding-pin,.finding-pin-card').length === 0
          && findingsToggle?.getAttribute('aria-pressed') === 'false'
          && Boolean(document.querySelector('[data-open-annotation="' + CSS.escape(smokeAnnotation.id) + '"]'));
        findingsToggle?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const markersRestore = Boolean(document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]'))
          && findingsToggle?.getAttribute('aria-pressed') === 'true';
        state.activeVersion = 'smoke-imported-proposal';
        versionSelect.value = state.activeVersion;
        const navigationSource = screens.find(screen => nodeIdsForScreen(screen).some(nodeId => nodes[nodeId]?.action?.type === 'navigate' && nodes[nodeId]?.action?.target !== screen.id));
        let prototypeNavigationWorks = true;
        let prototypeTreePreservesMode = true;
        let prototypeForcesInteraction = true;
        if (navigationSource) {
          const navigationNodeId = nodeIdsForScreen(navigationSource).find(nodeId => nodes[nodeId]?.action?.type === 'navigate' && nodes[nodeId]?.action?.target !== navigationSource.id);
          const navigationTarget = nodes[navigationNodeId]?.action?.target;
          state.interaction = 'inspect';
          setScreen(navigationSource.id, 'single');
          setView('prototype');
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          prototypeForcesInteraction = state.interaction === 'interact';
          document.querySelector('.stage [data-node-id="' + CSS.escape(navigationNodeId) + '"]')?.click();
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          prototypeNavigationWorks = state.view === 'prototype' && state.screen === navigationTarget;
          const treeTarget = screens.find(screen => screen.id !== state.screen)?.id;
          if (treeTarget) {
            document.querySelector('.screen-link[data-screen="' + CSS.escape(treeTarget) + '"]')?.click();
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            prototypeTreePreservesMode = state.view === 'prototype' && state.screen === treeTarget;
          }
        }

        const scenarioScreen = screens[0];
        const scenarioNodeId = scenarioScreen ? nodeIdsForScreen(scenarioScreen).find(nodeId => nodes[nodeId]?.type === 'text') : null;
        let screenScenarioControlsWork = true;
        let stateGalleryWorks = true;
        if (scenarioScreen && scenarioNodeId) {
          const originalScenarios = scenarioScreen.scenarios;
          scenarioScreen.scenarios = [...(Array.isArray(originalScenarios) ? originalScenarios : []), { id: 'smoke-fixture', label: 'Smoke fixture', nodeOverrides: { [scenarioNodeId]: { text: 'Scenario fixture visible' } } }];
          setScreen(scenarioScreen.id, 'single');
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const scenarioButton = document.querySelector('[data-screen-scenario="smoke-fixture"]');
          scenarioButton?.click();
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          screenScenarioControlsWork = Boolean(scenarioButton)
            && state.screenScenarioIds[scenarioScreen.id] === 'smoke-fixture'
            && document.querySelector('.stage [data-node-id="' + CSS.escape(scenarioNodeId) + '"]')?.textContent === 'Scenario fixture visible';
          setView('states');
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          stateGalleryWorks = state.view === 'states'
            && document.querySelectorAll('.state-gallery .state-panel').length === screenScenarios(scenarioScreen).length
            && document.querySelectorAll('.state-gallery .device').length === screenScenarios(scenarioScreen).length;
          if (originalScenarios === undefined) delete scenarioScreen.scenarios; else scenarioScreen.scenarios = originalScenarios;
          delete state.screenScenarioIds[scenarioScreen.id];
        }

        setScreen(screens[0].id, 'single');
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const resolvedMarkerHidden = !document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]');
        state.activeVersion = baselineVersion;
        versionSelect.value = state.activeVersion;
        renderView();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const baselineMarkerRestored = Boolean(document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]'));
        setView('compare');
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const resolvedMarkersStayOnBaseline = document.querySelectorAll('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]').length === 1;
        const versionArchitectureWorks = resolvedMarkerHidden && baselineMarkerRestored && resolvedMarkersStayOnBaseline;
        const markerBeforeZoom = document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]')?.getBoundingClientRect();
        const deviceBeforeZoom = document.querySelector('.device[data-version-id="' + CSS.escape(state.compareBaseVersion) + '"]')?.getBoundingClientRect();
        const anchorBeforeZoom = document.querySelector('.device[data-version-id="' + CSS.escape(state.compareBaseVersion) + '"] .device-content')?.getBoundingClientRect();
        const markerOffsetBeforeZoom = markerBeforeZoom && deviceBeforeZoom && anchorBeforeZoom ? (() => {
          const center = markerBeforeZoom.left + markerBeforeZoom.width / 2;
          const side = center < deviceBeforeZoom.left ? 'left' : 'right';
          const centerY = markerBeforeZoom.top + markerBeforeZoom.height / 2;
          return { side, x: center - (side === 'left' ? deviceBeforeZoom.left : deviceBeforeZoom.right), y: centerY - (anchorBeforeZoom.top + Math.min(12, anchorBeforeZoom.height / 2)), withinDeviceY: centerY >= deviceBeforeZoom.top - 1 && centerY <= deviceBeforeZoom.bottom + 1 };
        })() : null;
        setZoom(.8);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const zoomedMarker = document.querySelector('[data-open-finding="' + CSS.escape(smokeFinding.id) + '"]');
        const zoomedDevice = document.querySelector('.device[data-version-id="' + CSS.escape(state.compareBaseVersion) + '"]');
        const zoomedAnchor = zoomedDevice?.querySelector('.device-content');
        const markerRect = zoomedMarker?.getBoundingClientRect();
        const deviceRect = zoomedDevice?.getBoundingClientRect();
        const anchorRect = zoomedAnchor?.getBoundingClientRect();
        const markerOffsetAfterZoom = markerRect && deviceRect && anchorRect ? (() => {
          const center = markerRect.left + markerRect.width / 2;
          const side = center < deviceRect.left ? 'left' : 'right';
          const centerY = markerRect.top + markerRect.height / 2;
          return { side, x: center - (side === 'left' ? deviceRect.left : deviceRect.right), y: centerY - (anchorRect.top + Math.min(12, anchorRect.height / 2)), withinDeviceY: centerY >= deviceRect.top - 1 && centerY <= deviceRect.bottom + 1 };
        })() : null;
        const markerTracksZoom = Boolean(markerOffsetBeforeZoom && markerOffsetAfterZoom
          && markerOffsetBeforeZoom.side === markerOffsetAfterZoom.side
          && Math.abs(markerOffsetBeforeZoom.x) <= 70 && Math.abs(markerOffsetAfterZoom.x) <= 70
          && markerOffsetBeforeZoom.withinDeviceY && markerOffsetAfterZoom.withinDeviceY);
        const markerTrackMetrics = { before: markerOffsetBeforeZoom, after: markerOffsetAfterZoom };
        const markerGroups = new Map();
        for (const marker of document.querySelectorAll('.finding-pin[data-marker-device],.annotation-pin[data-marker-device]')) {
          const group = markerGroups.get(marker.dataset.markerDevice) || [];
          group.push(marker.getBoundingClientRect());
          markerGroups.set(marker.dataset.markerDevice, group);
        }
        let markerOverlaps = 0;
        for (const rects of markerGroups.values()) for (let first = 0; first < rects.length; first += 1) {
          for (let second = first + 1; second < rects.length; second += 1) {
            const x = Math.max(0, Math.min(rects[first].right, rects[second].right) - Math.max(rects[first].left, rects[second].left));
            const y = Math.max(0, Math.min(rects[first].bottom, rects[second].bottom) - Math.max(rects[first].top, rects[second].top));
            if (x * y > 1) markerOverlaps += 1;
          }
        }
        const markerLayoutStable = markerGroups.size > 0 && markerOverlaps === 0;
        const linkedMarker = document.querySelector('.finding-pin-leader + .finding-pin');
        const leadersHiddenByDefault = [...document.querySelectorAll('.finding-pin-leader')]
          .every(leader => Number(getComputedStyle(leader).opacity) === 0);
        linkedMarker?.click();
        await new Promise(resolve => setTimeout(resolve, 180));
        const openLeader = document.querySelector('.finding-pin-leader + .finding-pin-card');
        const leaderRevealsForOpenCard = !linkedMarker || Boolean(openLeader && Number(getComputedStyle(openLeader).opacity) === 1);
        document.querySelector('[data-collapse-finding]')?.click();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const markerLeaderWorks = leadersHiddenByDefault && leaderRevealsForOpenCard;
        const railCommandsWork = ['inspect', 'review', 'comments'].every(tab => Boolean(document.querySelector('.workbench-rail [data-inspector-tab="' + tab + '"]')))
          && document.querySelectorAll('.workbench-rail .rail-menu').length === 2
          && Boolean(document.querySelector('.workbench-rail .rail-menu.language-menu .locale-current'))
          && Boolean(document.querySelector('.workbench-rail .rail-menu .export-feedback'))
          && document.querySelectorAll('.canvas-tools [data-interaction]').length === 1
          && Boolean(document.querySelector('.canvas-tools [data-interaction="interact"]'))
          && !document.querySelector('.canvas-tools [data-canvas-layer]');
        const fileRailMenu = document.querySelector('.workbench-rail .rail-menu:not(.language-menu)');
        const languageRailMenu = document.querySelector('.workbench-rail .rail-menu.language-menu');
        const fileRailSummaryRect = fileRailMenu?.querySelector('summary')?.getBoundingClientRect();
        const fileRailIconRect = fileRailMenu?.querySelector('summary .icon')?.getBoundingClientRect();
        const railFileGeometryWorks = Boolean(fileRailMenu && fileRailSummaryRect && fileRailIconRect
          && document.querySelector('.workbench-rail')?.firstElementChild === fileRailMenu
          && Math.abs((fileRailSummaryRect.left + fileRailSummaryRect.right - fileRailIconRect.left - fileRailIconRect.right) / 2) <= .5
          && Math.abs((fileRailSummaryRect.top + fileRailSummaryRect.bottom - fileRailIconRect.top - fileRailIconRect.bottom) / 2) <= .5);
        fileRailMenu?.querySelector('summary')?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const fileRailMenuOpens = fileRailMenu?.open === true;
        languageRailMenu?.querySelector('summary')?.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        const railMenusAreExclusive = languageRailMenu?.open === true && fileRailMenu?.open === false;
        document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }));
        await new Promise(resolve => requestAnimationFrame(resolve));
        const railMenusDismiss = languageRailMenu?.open === false && fileRailMenu?.open === false;
        const railMenusWork = fileRailMenuOpens && railMenusAreExclusive && railMenusDismiss;
        state.annotations = state.annotations.filter(item => item.id !== smokeAnnotation.id);
        state.openAnnotationId = null;
        renderQueue();
        renderFindingMarkers();
        setWorkbenchLocale('en', { remember: false, updateLocation: false });
        const localeMetrics = { englishCanvas: document.querySelector('.canvas-tools')?.getAttribute('aria-label'), englishVersionTitle: document.querySelector('.header-version-picker')?.getAttribute('title'), englishCompare: document.querySelector('.mode-button[data-view="compare"] .button-label')?.textContent?.trim() };
        const englishLocaleWorks = document.documentElement.lang === 'en'
          && document.querySelector('.canvas-tools')?.getAttribute('aria-label') === 'Canvas tools'
          && document.querySelector('.header-version-picker')?.getAttribute('title') === 'Active mockup version'
          && document.querySelector('.mode-button[data-view="compare"] .button-label')?.textContent?.trim() === 'Compare';
        setWorkbenchLocale('ru', { remember: false, updateLocation: false });
        Object.assign(localeMetrics, { russianCanvas: document.querySelector('.canvas-tools')?.getAttribute('aria-label'), russianVersionTitle: document.querySelector('.header-version-picker')?.getAttribute('title'), russianCompare: document.querySelector('.mode-button[data-view="compare"] .button-label')?.textContent?.trim() });
        const russianLocaleRestores = document.documentElement.lang === 'ru'
          && document.querySelector('.canvas-tools')?.getAttribute('aria-label') === 'Инструменты холста'
          && document.querySelector('.header-version-picker')?.getAttribute('title') === 'Активная версия макета'
          && document.querySelector('.mode-button[data-view="compare"] .button-label')?.textContent?.trim() === 'Сравнить';
        for (const id of Object.keys(state.findingDecisions)) state.findingDecisions[id] = 'pending';
        state.findingDecisions[smokeFinding.id] = 'accepted';
        renderFindings();
        const sourceBeforeApproval = document.querySelector('.review-next-action')?.dataset.action !== 'source';
        approveActiveVersion();
        const sourceAfterApproval = document.querySelector('.review-next-action')?.dataset.action === 'source';
        const sourceRequest = typeof sourceRequestPayload === 'function' ? sourceRequestPayload() : null;
        const implementationHandoff = window.__uiPreviewDiagnostics?.agentHandoff?.('implement');
        const directFixEntryPoint = Boolean(document.querySelector('.fix-all-source'));
        const revisionVisible = Boolean(document.querySelector('.revision-badge')?.textContent?.trim());
        const declaredScenarioCases = screens.flatMap(screen => screenScenarios(screen).slice(1).map(scenario => [screen.id, scenario.id]));
        const screenScenarioDiagnosticsWork = declaredScenarioCases.every(([screenId, scenarioId]) => (state.diagnostics?.checks || []).some(check => check.scenarioId === 'state-matrix' && check.screenId === screenId && check.metrics?.screenScenarioId === scenarioId));

        setScreen(screens[0].id, 'single');
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const firstNode = document.querySelector('.stage .ui-node[data-node-id]');
        const selectedNodeId = firstNode?.dataset.nodeId || null;
        if (firstNode) selectNode(firstNode);
        setZoom(.9);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const selectionPreserved = !selectedNodeId || document.querySelector('[data-node-id="' + CSS.escape(selectedNodeId) + '"]')?.dataset.selected === 'true';

        setView('overview');
        setZoom(2);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const panStage = document.querySelector('.stage');
        panStage.scrollLeft = 0;
        panStage.scrollTop = 0;
        panStage.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 77, button: 1, buttons: 4, clientX: 420, clientY: 360 }));
        panStage.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 77, button: -1, buttons: 4, clientX: 350, clientY: 310 }));
        const middlePanWorks = panStage.scrollLeft >= 60
          && (panStage.scrollHeight <= panStage.clientHeight + 1 || panStage.scrollTop >= 40)
          && panStage.classList.contains('canvas-panning');
        const middlePanMetrics = { left: panStage.scrollLeft, top: panStage.scrollTop, scrollWidth: panStage.scrollWidth, scrollHeight: panStage.scrollHeight, clientWidth: panStage.clientWidth, clientHeight: panStage.clientHeight, active: panStage.classList.contains('canvas-panning') };
        panStage.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 77, button: 1, buttons: 0, clientX: 350, clientY: 310 }));
        const middlePanReleases = !panStage.classList.contains('canvas-panning');
        setZoom(1);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const stage = document.querySelector('.stage');
        const requestedScroll = Math.min(40, Math.max(0, stage.scrollWidth - stage.clientWidth));
        stage.scrollLeft = requestedScroll;
        renderView();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const renderedStage = document.querySelector('.stage');
        const expectedScroll = Math.min(requestedScroll, Math.max(0, renderedStage.scrollWidth - renderedStage.clientWidth));
        const scrollPreserved = Math.abs(renderedStage.scrollLeft - expectedScroll) <= 1;

        setInspectorTab('inspect');
        const inspectTabWorks = document.querySelector('[data-inspector-pane="inspect"]')?.hidden === false
          && [...document.querySelectorAll('[data-inspector-pane]')].filter(pane => !pane.hidden).length === 1;
        setInspectorTab('comments');
        const commentsTabWorks = document.querySelector('[data-inspector-pane="comments"]')?.hidden === false
          && [...document.querySelectorAll('[data-inspector-pane]')].filter(pane => !pane.hidden).length === 1;
        setInspectorTab('review');
        const reviewTabWorks = document.querySelector('[data-inspector-pane="review"]')?.hidden === false
          && [...document.querySelectorAll('[data-inspector-pane]')].filter(pane => !pane.hidden).length === 1;

        const search = document.querySelector('.screen-search');
        if (search) {
          search.value = 'узкое';
          search.dispatchEvent(new Event('input', { bubbles: true }));
        }
        const treeSearchWorks = [...document.querySelectorAll('.screen-link:not([hidden])')]
          .some(button => button.textContent.toLocaleLowerCase().includes('узкое'));
        if (search) {
          search.value = '';
          search.dispatchEvent(new Event('input', { bubbles: true }));
        }

        let compactPanelsExclusive = true;
        if (innerWidth <= 980) {
          state.sidebarOpen = true;
          state.inspectorOpen = false;
          applyPanelState();
          document.querySelector('.inspector-toggle')?.click();
          const rightOpenedAlone = state.inspectorOpen && !state.sidebarOpen;
          document.querySelector('.sidebar-toggle')?.click();
          const leftOpenedAlone = state.sidebarOpen && !state.inspectorOpen;
          compactPanelsExclusive = rightOpenedAlone && leftOpenedAlone;
          setInspectorTab('review');
        }
        return {
          totalBefore,
          totalAfter,
          actionableChecks,
          actionableGroups,
          autoReviewFindings,
          autoReviewButton: Boolean(document.querySelector('.run-review')),
          agentReviewButtonEnabled: document.querySelector('.open-agent-review')?.disabled === false,
          expertReviewButtonEnabled: document.querySelector('.export-review-request')?.disabled === false,
          expertRequestValid: expertRequest?.type === 'ui-design-workbench-expert-review-request'
            && expertRequest?.runtimeDiagnostics?.status === 'complete'
            && expertRequest?.screenIds?.length === screens.length
            && expertRequest?.requiredChatReport?.includes('plain numbered list')
            && expertRequest?.requiredChatReport?.includes('Do not add a duplicate plain-text report to the HTML')
            && expertRequest?.uiIr?.screens?.length === screens.length,
          expertHandoffValid: expertHandoff?.supported === true
            && expertHandoff?.provider === 'generic'
            && expertHandoff?.url === null
            && expertHandoff?.path === previewContext.artifactDir
            && expertHandoff?.prompt?.includes('ui-design-workbench')
            && expertHandoff?.prompt?.includes('Не изменяй исходный проект'),
          proposalHandoffValid: proposalHandoff?.supported === true
            && proposalHandoff?.context?.acceptedFindingIds?.length === selected
            && proposalHandoff?.context?.sourceChangeAllowed === false,
          implementationHandoffValid: implementationHandoff?.supported === true
            && implementationHandoff?.context?.sourceChangeAllowed === true
            && Boolean(implementationHandoff?.context?.projectRoot)
            && implementationHandoff?.prompt?.includes('В ЧАТЕ')
            && implementationHandoff?.prompt?.includes('Не запускай полное AI-ревью автоматически'),
          directFixEntryPoint,
          handoffPanelWorks,
          contextProposalAction,
          importWorks: Boolean(importWorks),
          compareVariantsWork,
          layerControlsWork: document.querySelectorAll('[data-canvas-layer]').length === 1
            && document.querySelectorAll('.mode-button[data-view]').length === 5
            && document.querySelectorAll('.compare-version-select').length === 2,
          prototypeForcesInteraction,
          prototypeNavigationWorks,
          prototypeTreePreservesMode,
          screenScenarioControlsWork,
          stateGalleryWorks,
          screenScenarioDiagnosticsWork,
          markerNumberMatches,
          markerPopoverOpens,
          markerPopoverCollapses,
          commentPopoverOpens,
          commentPopoverCollapses,
          userCommentHasDistinctColor,
          markersFollowComparedViews,
          railCommandsWork,
          railMenusWork,
          railFileGeometryWorks,
          markersToggleWork: markersHide && markersRestore,
          versionArchitectureWorks,
          markerTracksZoom,
          markerTrackMetrics,
          markerLayoutStable,
          markerOverlaps,
          markerLeaderWorks,
          middleMousePanWorks: middlePanWorks && middlePanReleases,
          middlePanMetrics,
          localeSwitchWorks: englishLocaleWorks && russianLocaleRestores,
          localeMetrics,
          reviewSectionsWork: ['summary', 'problems', 'changes'].every(section => Boolean(document.querySelector('[data-review-section="' + section + '"]'))),
          auditLinks: document.querySelectorAll('[data-audit-findings]').length,
          linkedVisible,
          selected,
          requestFindings: request?.acceptedFindingIds?.length || 0,
          runtimeActionable,
          reviewEntryPoint: Boolean(document.querySelector('[data-inspector-tab="review"]')),
          sourceBeforeApproval,
          sourceAfterApproval,
          sourceApprovalGuard: sourceRequest?.sourceChangeAllowed === true
            && Boolean(sourceRequest?.projectRoot)
            && Array.isArray(sourceRequest?.requiredChatReport)
            && sourceRequest?.requestedAction?.includes('do not run a full AI review'),
          revisionVisible,
          selectionPreserved,
          scrollPreserved,
          inspectTabWorks,
          commentsTabWorks,
          reviewTabWorks,
          treeSearchWorks,
          compactPanelsExclusive,
        };
      })()`,
      returnByValue: true,
      awaitPromise: true,
    });
    if (workflowResponse.exceptionDetails) {
      throw new Error(`Review workflow evaluation failed: ${workflowResponse.exceptionDetails.exception?.description || workflowResponse.exceptionDetails.text || 'unknown error'}`);
    }
    const workflow = workflowResponse.result?.value || {};
    if (!workflow.reviewEntryPoint) throw new Error('Review workflow entry point is missing');
    if (workflow.totalBefore > 0 && (
      !workflow.auditLinks || !workflow.linkedVisible || workflow.totalAfter !== workflow.totalBefore + workflow.actionableGroups + 1
      || workflow.autoReviewFindings !== workflow.actionableGroups + 1 || !workflow.autoReviewButton
      || !workflow.agentReviewButtonEnabled || !workflow.expertReviewButtonEnabled || !workflow.expertRequestValid
      || !workflow.expertHandoffValid || !workflow.proposalHandoffValid || !workflow.implementationHandoffValid || !workflow.directFixEntryPoint
      || !workflow.handoffPanelWorks
      || !workflow.contextProposalAction || !workflow.importWorks || !workflow.compareVariantsWork || !workflow.reviewSectionsWork
      || !workflow.layerControlsWork || !workflow.prototypeForcesInteraction || !workflow.prototypeNavigationWorks || !workflow.prototypeTreePreservesMode
      || !workflow.screenScenarioControlsWork || !workflow.stateGalleryWorks || !workflow.screenScenarioDiagnosticsWork || !workflow.markerNumberMatches || !workflow.markerPopoverOpens
      || !workflow.markerPopoverCollapses || !workflow.commentPopoverOpens || !workflow.commentPopoverCollapses
      || !workflow.userCommentHasDistinctColor || !workflow.markersFollowComparedViews || !workflow.railCommandsWork || !workflow.railMenusWork || !workflow.railFileGeometryWorks
      || !workflow.markersToggleWork || !workflow.versionArchitectureWorks
      || !workflow.markerTracksZoom || !workflow.markerLayoutStable || !workflow.markerLeaderWorks || !workflow.middleMousePanWorks || !workflow.localeSwitchWorks
      || workflow.selected !== 1 || workflow.requestFindings !== 1 || !workflow.runtimeActionable
      || !workflow.sourceBeforeApproval || !workflow.sourceAfterApproval
      || !workflow.sourceApprovalGuard || !workflow.revisionVisible
      || !workflow.selectionPreserved || !workflow.scrollPreserved
      || !workflow.inspectTabWorks || !workflow.commentsTabWorks || !workflow.reviewTabWorks
      || !workflow.treeSearchWorks || !workflow.compactPanelsExclusive
    )) {
      throw new Error(`Review workflow smoke failed: ${JSON.stringify(workflow)}`);
    }
    const fixedProfiles = (report.profiles || []).filter(item => item.viewport && item.viewport !== 'current');
    const measuredProfiles = new Set((report.checks || []).map(item => item.metrics?.profileId).filter(Boolean));
    if (fixedProfiles.length < 2 || fixedProfiles.some(item => !measuredProfiles.has(item.id))) {
      throw new Error(`Viewport profile smoke failed: configured=${fixedProfiles.map(item => item.id)} measured=${[...measuredProfiles]}`);
    }
    const captureState = { ...initialVisualState };
    if (args.captureView) captureState.view = args.captureView;
    if (args.captureScreen) captureState.screen = args.captureScreen;
    if (args.captureLeftPanel) captureState.sidebarOpen = args.captureLeftPanel === 'open';
    if (args.captureRightPanel) captureState.inspectorOpen = args.captureRightPanel === 'open';
    if (args.captureInspectorTab) captureState.inspectorTab = args.captureInspectorTab;
    if (args.captureReviewSection) captureState.reviewSection = args.captureReviewSection;
    if (args.viewportWidth <= 980 && captureState.sidebarOpen && captureState.inspectorOpen) captureState.sidebarOpen = false;
    await cdp.call('Runtime.evaluate', {
      expression: `(() => {
        const snapshot = ${JSON.stringify(captureState)};
        if (!screens.some(item => item.id === snapshot.screen)) snapshot.screen = screens[0]?.id;
        Object.assign(state, snapshot);
        versionSelect.value = state.activeVersion;
        writeLocation(false);
        applyPanelState();
        syncInteractionButtons();
        renderFindings();
        renderQueue();
        renderFixQueue();
        renderReviewSections();
         renderCoverage();
         renderReviewHistory();
         renderImportStatus();
         renderAgentHandoff();
         renderView();
        document.querySelector('[data-inspector-pane="review"]')?.scrollTo({ top: 0, behavior: 'instant' });
        const toast = document.querySelector('.workbench-toast');
        if (toast) { toast.classList.remove('visible'); toast.textContent = ''; }
      })()`,
      returnByValue: true,
    });
    await delay(100);
    if (args.screenshot) {
      await cdp.call('Page.enable');
      const shot = await cdp.call('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
      fs.writeFileSync(path.resolve(args.screenshot), Buffer.from(shot.data, 'base64'));
    }
    if (args.geometryOutput) {
      const geometryResponse = await cdp.call('Runtime.evaluate', {
        expression: `(() => {
          const rect = element => {
            if (!element) return null;
            const value = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
              x: Math.round(value.x * 100) / 100,
              y: Math.round(value.y * 100) / 100,
              width: Math.round(value.width * 100) / 100,
              height: Math.round(value.height * 100) / 100,
              visible: style.display !== 'none' && style.visibility !== 'hidden' && value.width > 0 && value.height > 0,
              overflowX: style.overflowX,
              overflowY: style.overflowY,
            };
          };
          const selectors = {
            rail: '.workbench-rail',
            leftPanel: '.sidebar',
            documentBar: '.toolbar',
            stage: '.stage',
            canvasTools: '.canvas-tools',
            zoomControls: '.zoom-controls',
            rightPanel: '.inspector',
            activeInspectorPane: '[data-inspector-pane]:not([hidden])',
          };
          const elements = Object.fromEntries(Object.entries(selectors).map(([key, selector]) => [key, rect(document.querySelector(selector))]));
          document.querySelectorAll('[data-screen-card]').forEach((element, index) => { elements['screenCard:' + (element.dataset.screenCard || index)] = rect(element); });
          const cards = Object.entries(elements).filter(([key, value]) => key.startsWith('screenCard:') && value?.visible);
          const overlaps = [];
          for (let first = 0; first < cards.length; first += 1) for (let second = first + 1; second < cards.length; second += 1) {
            const [aKey, a] = cards[first], [bKey, b] = cards[second];
            if (a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y) overlaps.push([aKey, bKey]);
          }
          return { version: 1, viewport: { width: innerWidth, height: innerHeight }, view: state.view, screen: state.screen, zoom: state.computedZoom, sidebarOpen: state.sidebarOpen, inspectorOpen: state.inspectorOpen, inspectorTab: state.inspectorTab, elements, overlaps };
        })()`,
        returnByValue: true,
      });
      fs.writeFileSync(path.resolve(args.geometryOutput), JSON.stringify(geometryResponse.result?.value || {}, null, 2) + '\n');
    }
    await cdp.call('Page.enable');
    const storageKeyResponse = await cdp.call('Runtime.evaluate', { expression: 'storageKey', returnByValue: true });
    const reviewStorageKey = storageKeyResponse.result?.value;
    if (!reviewStorageKey) throw new Error('Review storage key is unavailable');
    const staleInjection = await cdp.call('Page.addScriptToEvaluateOnNewDocument', {
      source: `localStorage.setItem(${JSON.stringify(reviewStorageKey)}, JSON.stringify({revision:'stale-smoke',annotations:[],findingDecisions:{}}));`,
    });
    await cdp.call('Page.navigate', { url: pathToFileURL(input).href });
    const revisionDeadline = Date.now() + 15000;
    let staleNoticeVisible = false;
    while (Date.now() < revisionDeadline) {
      const staleResponse = await cdp.call('Runtime.evaluate', {
        expression: "document.readyState === 'complete' && document.querySelector('.revision-notice')?.hidden === false",
        returnByValue: true,
      });
      staleNoticeVisible = staleResponse.result?.value === true;
      if (staleNoticeVisible) break;
      await delay(100);
    }
    await cdp.call('Page.removeScriptToEvaluateOnNewDocument', { identifier: staleInjection.identifier });
    if (!staleNoticeVisible) throw new Error('Stale revision notice did not appear');
    const resetResponse = await cdp.call('Runtime.evaluate', {
      expression: `(() => {
        document.querySelector('.discard-review-state')?.click();
        const stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
        return document.querySelector('.revision-notice')?.hidden === true && stored.revision !== 'stale-smoke';
      })()`,
      returnByValue: true,
    });
    if (resetResponse.result?.value !== true) throw new Error('Stale revision reset failed');
    if (args.output) fs.writeFileSync(path.resolve(args.output), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    const summary = report.summary || {};
    console.log(`Diagnostics complete: pass=${summary.pass || 0} warning=${summary.warning || 0} fail=${summary.fail || 0} checks=${report.checks?.length || 0}`);
    console.log(`Review workflow: findings=${workflow.totalAfter || 0} auditLinks=${workflow.auditLinks || 0} selected=${workflow.selected || 0} requestFindings=${workflow.requestFindings || 0} profiles=${fixedProfiles.length}`);
    if (args.failOnFindings && (summary.fail || 0) > 0) process.exitCode = 1;
  } finally {
    try { socket?.close(); } catch (_) {}
    try { browser.kill(); } catch (_) {}
    if (browser.exitCode === null) await Promise.race([
      new Promise(resolve => browser.once('exit', resolve)),
      delay(1500),
    ]);
    let cleanupError = null;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try { fs.rmSync(profile, { recursive: true, force: true }); cleanupError = null; break; }
      catch (error) { cleanupError = error; await delay(150 * (attempt + 1)); }
    }
    if (cleanupError) console.warn(`Temporary browser profile could not be removed: ${cleanupError.message}`);
  }
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 2;
});
