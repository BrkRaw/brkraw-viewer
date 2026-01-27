

# Label Paint Demo - Developer Guide

이 문서는 `label_paint_demo.py`를 중심으로 **Viewport**, **LabelMapPainter**, 그리고 Demo App 전체 구조를 개발자가 빠르게 이해하고 확장할 수 있도록 설명한다.

---

## 1. 전체 구조 개요

이 데모는 다음과 같은 명확한 책임 분리를 따른다.

```
[State / Controller]
        |
        v
[LabelMapPainter]  <->  [ViewportCanvas]
        |
        v
   label_map (numpy)
```

- **State / Controller (Demo에서는 LabelPaintDemo)**
  - label volume / label metadata(id, name, color)의 소유자
  - slice 선택, label 편집 결과를 최종적으로 보관

- **LabelMapPainter**
  - 브러시, hover preview, stroke 처리
  - numpy label matrix에 직접 write

- **ViewportCanvas**
  - underlay image 표시
  - overlay RGBA 렌더링
  - 좌표 변환(canvas <-> image)

---

## 2. ViewportCanvas

### 역할

`ViewportCanvas`는 **순수 UI 컴포넌트**다.

- underlay 이미지 표시 (2D slice)
- overlay RGBA 이미지 표시
- brush preview 렌더링
- resize / scale 대응

### 주요 책임

- 픽셀 좌표계 유지
- canvas 좌표를 image index로 변환
- 실제 데이터 변경은 절대 하지 않음

### 주요 API

- `set_image(image: np.ndarray)`
- `set_overlay_rgba(rgba: np.ndarray | None)`
- `set_brush_preview(r, c, size, shape, color, show=True)`
- `canvas_to_image(x, y) -> (r, c) | None`

---

## 3. LabelMapPainter

### 역할

LabelMapPainter는 **label painting 로직의 핵심**이다.

- 브러시 stroke 처리
- hover preview 제어
- label matrix write
- overlay RGBA 생성

중요한 점은 **canvas에 직접 그림을 그리지 않는다**는 것이다.
모든 결과는 numpy matrix에 기록되고, viewport는 이를 렌더링만 한다.

### 핵심 설계 포인트

- label_map은 numpy view (in-place 수정)
- painter는 slice-level editor
- 3D volume의 소유권은 painter가 갖지 않음

### 주요 상태

- `label_map: np.ndarray` (2D view)
- `slice_axis`, `slice_index`
- `active_label`
- `erase_label`
- `brush.radius`, `brush.shape`
- `lut_rgba` (label -> RGBA)

### 주요 메서드

- `set_label_volume(volume, axis, index)`
- `set_active_label(label)`
- `set_label_color(label, rgb, alpha)`
- `refresh_overlay_full()`
- `attach() / detach()`

---

## 4. Label Paint Demo (label_paint_demo.py)

### 목적

이 파일은 **전체 라벨링 파이프라인의 참조 구현(reference implementation)**이다.

- 실제 앱에서 Controller / State로 이동될 로직들이 여기 모여 있다.
- 기능 검증과 UX 실험이 목적이다.

### 포함 기능

- 브러시 선택 (circle / square)
- erase mode
- label selector (Menubutton)
- label add / delete
- label rename
- label id 변경 (Change ID)
- label merge / replace
- label color 변경

---

## 5. Label Editor Popup

### 기능

Label Editor는 ITK-SNAP 스타일의 간단한 label 관리 UI다.

#### 지원 동작

- Add label
- Delete label
- Rename label
- Change ID
- Merge / Replace (ID 충돌 시)

#### Matrix 동기화 규칙

- **Rename**: metadata(name)만 변경
- **Change ID (no conflict)**:
  - matrix: old -> new
  - metadata: old name/color -> new
- **Merge**:
  - matrix: old -> new
  - metadata: new 유지, old 제거
- **Replace**:
  - matrix: new -> 0, old -> new
  - metadata: new 유지, old 제거
- **Delete**:
  - matrix: label -> 0
  - metadata 제거

---

## 6. State 설계 권장안 (실제 앱 적용 시)

Demo에서는 state가 `LabelPaintDemo` 내부에 있지만,
실제 앱에서는 다음과 같이 분리하는 것이 권장된다.

```python
class LabelState:
    label_volume: np.ndarray  # 3D
    label_names: dict[int, str]
    label_colors: dict[int, RGBA]
    slice_axis: int
    slice_index: int
```

- Painter는 slice view만 받는다
- 모든 label 변경은 state에 반영된다
- undo/redo, save/load는 state 레벨에서 처리

---

## 7. 확장 포인트

- 3D orthogonal view (axial/sagittal/coronal)
- undo / redo stack
- brush interpolation
- QC metric 계산
- NIfTI / BIDS export

---

## 8. 철학 요약

- Viewport는 그리지 않는다, 보여준다
- Painter는 UI가 아니다, 편집기다
- State가 진짜 데이터를 소유한다

이 원칙을 지키면 구조가 커져도 무너지지 않는다.