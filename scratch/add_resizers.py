import re
import sys

def main():
    file_path = "/home/ed/thesis/taltech-uav-mcp-server/src/uav_mcp_server/dashboard_ui.py"
    with open(file_path, "r") as f:
        content = f.read()

    # 1. CSS changes
    resizer_css = """
  /* ── Resizers ── */
  .resizer-v {
    position: absolute;
    width: 16px;
    cursor: col-resize;
    z-index: 50;
    transform: translateX(-50%);
  }
  .resizer-v.right {
    transform: translateX(50%);
  }
  .resizer-h {
    position: absolute;
    height: 16px;
    cursor: row-resize;
    z-index: 50;
    transform: translateY(50%);
  }
  .resizer-v:hover::after, .resizer-h:hover::after,
  .resizer-v.dragging::after, .resizer-h.dragging::after {
    content: '';
    position: absolute;
    background: var(--accent);
    opacity: 0.5;
  }
  .resizer-v::after { left: 7px; right: 7px; top: 0; bottom: 0; }
  .resizer-h::after { top: 7px; bottom: 7px; left: 0; right: 0; }

  /* ── Dashboard Grid ── */
  .dashboard {
    position: relative;"""
    
    content = content.replace("/* ── Dashboard Grid ── */\n  .dashboard {\n", resizer_css)

    # 2. HTML changes
    html_resizers = """  <main class="dashboard" id="dashboard">
    <!-- ═══ Drag Resizers ═══ -->
    <div id="drag-v-left" class="resizer-v"></div>
    <div id="drag-v-right" class="resizer-v right"></div>
    <div id="drag-h" class="resizer-h"></div>"""
    
    content = content.replace('<main class="dashboard">', html_resizers)

    # 3. JS changes
    js_resizers = """
  /* ── Layout Resizers ── */
  function initResizers() {
    var dashboard = $('dashboard');
    if (!dashboard) return;
    
    var colLeft = 320;
    var colRight = 340;
    var rowBottom = 280;
    var gap = 16;
    
    var dragVLeft = $('drag-v-left');
    var dragVRight = $('drag-v-right');
    var dragH = $('drag-h');

    function updateGrid() {
      dashboard.style.gridTemplateColumns = colLeft + 'px 1fr ' + colRight + 'px';
      dashboard.style.gridTemplateRows = '1fr ' + rowBottom + 'px';
      
      dragVLeft.style.left = colLeft + (gap/2) + 'px';
      dragVLeft.style.bottom = '0px';
      dragVLeft.style.height = rowBottom + 'px';
      
      dragVRight.style.right = colRight + (gap/2) + 'px';
      dragVRight.style.top = '0px';
      dragVRight.style.bottom = '0px';
      
      dragH.style.bottom = rowBottom + (gap/2) + 'px';
      dragH.style.left = '0px';
      dragH.style.right = '0px';
      
      if (appState.mapReady && appState.map) {
        window.setTimeout(function() { appState.map.resize(); }, 50);
      }
    }

    function attachDrag(el, type) {
      if (!el) return;
      var startVal = 0;
      var startCoord = 0;
      var rect = null;

      function onPointerMove(e) {
        if (type === 'v-left') {
          var newLeft = startVal + (e.clientX - startCoord);
          colLeft = Math.max(200, Math.min(newLeft, dashboard.clientWidth - colRight - 200));
        } else if (type === 'v-right') {
          var newRight = startVal - (e.clientX - startCoord);
          colRight = Math.max(200, Math.min(newRight, dashboard.clientWidth - colLeft - 200));
        } else if (type === 'h') {
          var newBottom = startVal - (e.clientY - startCoord);
          rowBottom = Math.max(150, Math.min(newBottom, dashboard.clientHeight - 200));
        }
        updateGrid();
      }

      function onPointerUp(e) {
        el.classList.remove('dragging');
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
        document.body.style.cursor = '';
      }

      el.addEventListener('pointerdown', function(e) {
        e.preventDefault();
        el.classList.add('dragging');
        rect = dashboard.getBoundingClientRect();
        if (type === 'v-left') startVal = colLeft;
        if (type === 'v-right') startVal = colRight;
        if (type === 'h') startVal = rowBottom;
        startCoord = type === 'h' ? e.clientY : e.clientX;
        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
        document.body.style.cursor = type === 'h' ? 'row-resize' : 'col-resize';
      });
    }

    attachDrag(dragVLeft, 'v-left');
    attachDrag(dragVRight, 'v-right');
    attachDrag(dragH, 'h');
    
    updateGrid();
    window.addEventListener('resize', updateGrid);
  }

  /* ── Tab Switching ── */"""

    content = content.replace("/* ── Tab Switching ── */", js_resizers)
    
    # 4. Add to initUI
    content = content.replace("initMapTargetControls();\n    updateManualUI();", "initMapTargetControls();\n    initResizers();\n    updateManualUI();")

    with open(file_path, "w") as f:
        f.write(content)
        
    print("Resizers added successfully.")

if __name__ == "__main__":
    main()
