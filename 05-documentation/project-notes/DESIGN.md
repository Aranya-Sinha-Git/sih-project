# Design direction

**Mode:** OPERATE — safety decisions need scanable density and native dashboard expectations.

The shell uses a near-black blue sidebar (`#122027`) to anchor a warm technical canvas (`#f5f4ef`). Tables and detail panels use restrained white surfaces with hairline slate borders; only high-priority records gain a warm tinted panel. The visual reference board established this direction before implementation.

Typography is Inter/system sans for fast reading, with compact tabular numerals for metrics. Spacing follows 4/8/12/16/24/32px tokens. Corners are 6px; shadows are avoided except on transient menus. The alert palette is semantic: critical red, watch amber, stable teal and neutral slate, always paired with a label/icon. Charts are thin, quiet, and use direct labels. Lucide icons are functional, never decorative.

Controls are compact, keyboard-visible, and have explicit labels. Motion is limited to opacity/position transitions under 160ms and is disabled for reduced motion. Loading, empty, error and offline states retain context and offer a specific next action. Long names, missing fields, narrow layouts and dense tables are deliberate first-class states.
