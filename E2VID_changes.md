# Changes for CPU/GPU Compatibility

The following changes were made to enable the code to run on both CPU and GPU environments automatically.

## 1. `image_reconstructor.py` 

**Context:** `ImageReconstructor.__init__`

```diff
- self.use_gpu = options.use_gpu
+ self.use_gpu = options.use_gpu and torch.cuda.is_available()

```

---

## 2. `run_reconstruction.py`

**Context:** `__main__`

```diff
- parser.set_defaults(compute_voxel_grid_on_cpu=False)
+ parser.set_defaults(compute_voxel_grid_on_cpu=True)

```

---

## 3. `utils/loading_utils.py`

**Context:** `load_model`

```diff
- raw_model = torch.load(path_to_model)
+ if torch.cuda.is_available():
+     raw_model = torch.load(path_to_model)
+ else:
+     raw_model = torch.load(path_to_model, map_location=torch.device('cpu'))

```

---

## 4. `utils/timers.py`

**Context:** `CudaTimer.__init__`

```diff
- self.start = torch.cuda.Event(enable_timing=True)
- self.end = torch.cuda.Event(enable_timing=True)
+
+ try:
+     from torch.cuda import Event as CudaEvent
+     if torch.cuda.is_available():
+         self.cuda_supported = True
+     else:
+         self.cuda_supported = False
+ except Exception:
+     self.cuda_supported = False
+ 
+ if not self.cuda_supported:
+     class CudaEvent:
+         def __init__(self, *args, **kwargs): pass
+         def record(self, *args, **kwargs): pass
+         def elapsed_time(self, *args, **kwargs): return 0
+
+ self.start = CudaEvent(enable_timing=True) if self.cuda_supported else CudaEvent()
+ self.end   = CudaEvent(enable_timing=True) if self.cuda_supported else CudaEvent()

```

**Context:** `CudaTimer.__exit__`

```diff
  self.end.record()
- torch.cuda.synchronize()
- cuda_timers[self.timer_name].append(self.start.elapsed_time(self.end))
+ if self.cuda_supported:
+     import torch
+     torch.cuda.synchronize()
+     cuda_timers[self.timer_name].append(self.start.elapsed_time(self.end))
+ else:
+     cuda_timers[self.timer_name].append(0)

```