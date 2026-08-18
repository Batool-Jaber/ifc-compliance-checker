# IfcOpenShell — المرجع الشامل

مرجع تقني كامل لمكتبة IfcOpenShell، من الأساسيات إلى التطبيق العملي، مُعدّ خصيصًا ليخدم مشروع IFC Compliance Checker.

---

## الفصل 1: مقدمة عامة

### ما هي IfcOpenShell؟
مكتبة مفتوحة المصدر (رخصة LGPL) مكتوبة بالأساس بلغة C++، مع واجهات (bindings) لبايثون و C#. هي المكتبة المرجعية الأكثر انتشارًا للتعامل البرمجي مع ملفات IFC (Industry Foundation Classes) — سواء بالقراءة، الكتابة، التعديل، أو معالجة الهندسة ثلاثية الأبعاد.

### لماذا هي الخيار الافتراضي في مجال BIM المفتوح؟
- مجانية بالكامل ومفتوحة المصدر، بعكس أغلب أدوات Autodesk أو Bentley.
- تدعم معظم إصدارات مخطط IFC: IFC2X3، IFC4، IFC4X1، IFC4X3.
- هي المحرك الذي يقف خلف إضافة **Bonsai** (سابقًا BlenderBIM) الشهيرة داخل Blender.
- مجتمع نشط وتوثيق رسمي محدث باستمرار.

### التثبيت
```bash
pip install ifcopenshell
```
> ملاحظة: بعض الوظائف المتقدمة (مثل geometry processing الكامل) تعتمد على مكتبات إضافية مثل OpenCascade، لكنها غالبًا تُضمّن تلقائيًا مع الحزمة الحديثة على PyPI.

للتحقق من التثبيت:
```python
import ifcopenshell
print(ifcopenshell.version)
```

---

## الفصل 2: أساسيات نموذج بيانات IFC

قبل الغوص بالمكتبة، لازم تفهم كيف يُبنى ملف IFC نفسه من الداخل، لأن كل دوال المكتبة مبنية على هذا المنطق.

### 2.1 الـ Entity
كل عنصر داخل الملف — سواء جدار، غرفة، أو حتى نقطة هندسية — هو **Entity** له:
- **نوع (Class)** محدد مسبقًا في مخطط IFC، مثل `IfcWall`, `IfcSpace`, `IfcWindow`.
- **معرّف فريد عالمي (GlobalId)** بصيغة IFC GUID (22 حرف مضغوط).
- **Attributes** مباشرة (اسم، وصف...).
- **علاقات (Relationships)** تربطه بعناصر أخرى.

### 2.2 التسلسل الهرمي المكاني (Spatial Structure)
كل مشروع IFC يُبنى وفق تسلسل هرمي إلزامي تقريبًا:
```
IfcProject
 └── IfcSite
      └── IfcBuilding
           └── IfcBuildingStorey
                └── IfcSpace (الغرفة)
                     └── العناصر (جدران، أبواب، نوافذ...)
```
هذا التسلسل ضروري جدًا لمشروعك لأنه هو الذي يسمح لك لاحقًا بمعرفة "أي عناصر تنتمي لأي غرفة".

### 2.3 الوراثة في مخطط IFC
المخطط نفسه مبني بمنطق OOP:
```
IfcRoot
 └── IfcObjectDefinition
      └── IfcObject
           └── IfcProduct
                └── IfcElement
                     └── IfcBuildingElement
                          └── IfcWall / IfcWindow / IfcColumn ...
```
هذا يعني أن أي دالة تتعامل مع `IfcElement` بشكل عام، تشتغل تلقائيًا على الجدران والنوافذ والأعمدة كلهم.

### 2.4 Property Sets و Quantity Sets
- **Property Sets (Psets)**: خصائص إضافية غير هندسية (مثل المادة، مقاومة الحريق).
- **Quantity Sets (Qtos)**: قيم كمية محسوبة مسبقًا (مساحة، حجم، طول) — قد تكون موجودة جاهزة في الملف، أو تحتاج تحسبها بنفسك من الهندسة.

### 2.5 الوحدات (Units)
ملفات IFC لا تفترض وحدة قياس ثابتة؛ الوحدة مُعرّفة داخل `IfcUnitAssignment`. من الأخطاء الشائعة نسيان تحويل الوحدات (مثلاً ملم إلى متر) عند حساب المساحات.

---

## الفصل 3: البنية العامة لمكتبة IfcOpenShell (Modules)

| الموديول | الوظيفة |
|---|---|
| `ifcopenshell` | الوظائف الأساسية: فتح/إنشاء/حفظ الملف، البحث عن الكائنات |
| `ifcopenshell.api` | واجهة عالية المستوى لإنشاء وتعديل العناصر بسهولة |
| `ifcopenshell.geom` | استخراج ومعالجة الهندسة ثلاثية الأبعاد |
| `ifcopenshell.util` | دوال مساعدة جاهزة (حساب مساحات، Placement، Psets...) |
| `ifcopenshell.validate` | التحقق من صحة الملف مقابل مخطط IFC الرسمي |
| `ifcopenshell.template` | إنشاء مشروع IFC فارغ بالبنية الأساسية جاهزة |
| `ifcopenshell.express` | التعامل مع تعريفات مخطط IFC نفسه (نادرًا ما تحتاجه مباشرة) |

---

## الفصل 4: الموديول الأساسي — `ifcopenshell`

### 4.1 فتح وإنشاء الملفات
```python
import ifcopenshell

# فتح ملف موجود
model = ifcopenshell.open("existing.ifc")

# إنشاء ملف فارغ بمخطط معين
model = ifcopenshell.file(schema="IFC4")
```

### 4.2 إنشاء Entity يدويًا (Low-level)
```python
wall = model.create_entity(
    "IfcWall",
    GlobalId=ifcopenshell.guid.new(),
    Name="Wall-01",
    OwnerHistory=None
)
```
> ملاحظة: هذه الطريقة تعطيك تحكم كامل، لكنها أكثر عرضة للأخطاء لأنك مسؤول يدويًا عن كل Attribute وكل علاقة.

### 4.3 البحث عن العناصر (Querying)
```python
# كل الجدران بالملف
walls = model.by_type("IfcWall")

# كل الفراغات (الغرف)
spaces = model.by_type("IfcSpace")

# عنصر واحد عبر GlobalId
element = model.by_guid("2O2Fr$t4X7Zf8NOew3FLOH")

# عنصر واحد عبر رقم التسلسل الداخلي (id)
element = model.by_id(145)
```

### 4.4 قراءة وتعديل الـ Attributes
```python
print(wall.Name)
wall.Name = "External Wall - North"
```

### 4.5 حفظ الملف
```python
model.write("output/building.ifc")
```

### 4.6 حذف Entity
```python
model.remove(wall)
```
> تحذير: الحذف اليدوي قد يترك علاقات "يتيمة" (orphan relationships) تشير لعنصر محذوف؛ يُفضّل استخدام `ifcopenshell.api.run("root.remove_product", ...)` بدلاً من الحذف المباشر لأنها تنظف العلاقات تلقائيًا.

---

## الفصل 5: `ifcopenshell.api` — الواجهة العالية المستوى

هذا هو الموديول الموصى به لإنشاء وتعديل العناصر لأنه يتولى إدارة العلاقات والقيم الافتراضية نيابة عنك، ويقلل الأخطاء بشكل كبير.

### 5.1 إنشاء مشروع من الصفر
```python
import ifcopenshell.api

model = ifcopenshell.api.run("project.create_file", version="IFC4")

project = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcProject", name="My Project")

ifcopenshell.api.run("unit.assign_unit", model)  # يضبط الوحدات الافتراضية (متر)

context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
body_context = ifcopenshell.api.run("context.add_context", model,
    context_type="Model", context_identifier="Body",
    target_view="MODEL_VIEW", parent=context)
```

### 5.2 بناء التسلسل المكاني
```python
site = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcSite", name="Site")
building = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcBuilding", name="Building")
storey = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcBuildingStorey", name="Ground Floor")

ifcopenshell.api.run("aggregate.assign_object", model,
    products=[site], relating_object=project)
ifcopenshell.api.run("aggregate.assign_object", model,
    products=[building], relating_object=site)
ifcopenshell.api.run("aggregate.assign_object", model,
    products=[storey], relating_object=building)
```

### 5.3 إنشاء عنصر وربطه بالطابق
```python
wall = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcWall", name="Wall-01")

ifcopenshell.api.run("spatial.assign_container", model,
    products=[wall], relating_structure=storey)
```

### 5.4 إعطاء الجدار هندسة فعلية (Geometry)
```python
representation = ifcopenshell.api.run("geometry.add_wall_representation",
    model, context=body_context,
    length=5.0, height=3.0, thickness=0.2)

ifcopenshell.api.run("geometry.assign_representation", model,
    product=wall, representation=representation)
```

### 5.5 تحديد موقع العنصر (Placement)
```python
ifcopenshell.api.run("geometry.edit_object_placement", model,
    product=wall, matrix=your_transformation_matrix)
```

### 5.6 إنشاء فتحة ونافذة (مهم جدًا لمشروعك)
عملية إضافة نافذة داخل جدار تتطلب خطوتين منطقيتين:
1. إنشاء **فتحة (IfcOpeningElement)** داخل الجدار.
2. إنشاء **IfcWindow** وربطه بالفتحة عبر علاقة `IfcRelFillsElement`.

```python
opening = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcOpeningElement", name="Window Opening")
# ... إعطاء الفتحة هندسة وموقع مشابه للجدار

ifcopenshell.api.run("void.add_opening", model,
    opening=opening, element=wall)

window = ifcopenshell.api.run("root.create_entity", model,
    ifc_class="IfcWindow", name="Window-01")
# ... إعطاء النافذة هندسة

ifcopenshell.api.run("void.add_filling", model,
    opening=opening, element=window)
```

### 5.7 إضافة Property Sets مخصصة
```python
pset = ifcopenshell.api.run("pset.add_pset", model,
    product=wall, name="Pset_WallCommon")

ifcopenshell.api.run("pset.edit_pset", model,
    pset=pset, properties={"FireRating": "2HR", "IsExternal": True})
```

---

## الفصل 6: `ifcopenshell.geom` — معالجة الهندسة ثلاثية الأبعاد

هذا الموديول هو الأهم لمشروعك تحديدًا، لأن حساب المساحات والارتفاعات يعتمد عليه.

### 6.1 استخراج شكل هندسي من عنصر
```python
import ifcopenshell.geom

settings = ifcopenshell.geom.settings()
settings.set(settings.USE_WORLD_COORDS, True)  # إحداثيات مطلقة بدل محلية

shape = ifcopenshell.geom.create_shape(settings, element)

verts = shape.geometry.verts   # قائمة إحداثيات النقاط (x,y,z مسطحة)
faces = shape.geometry.faces   # قائمة الأوجه (مؤشرات على verts)
edges = shape.geometry.edges
```

### 6.2 تحويل النقاط إلى Bounding Box
غالبًا تحتاج تحسب أبعاد العنصر بسرعة بدون معالجة معقدة:
```python
xs = verts[0::3]
ys = verts[1::3]
zs = verts[2::3]

width  = max(xs) - min(xs)
depth  = max(ys) - min(ys)
height = max(zs) - min(zs)
```
> تحذير: الـ Bounding Box كافٍ للأشكال المستطيلة البسيطة (كحالة مشروعك)، لكنه غير دقيق للأشكال المعقدة أو غير المنتظمة.

### 6.3 حساب مساحة مضلع (لحساب مساحة الغرفة)
مساحة الغرفة تُحسب عادة من مضلع الأرضية (Footprint)، إما عبر:
- استخراج الهندسة الكاملة وأخذ الوجه السفلي فقط، أو
- استخدام `ifcopenshell.util.shape` الذي يوفر دوال جاهزة (انظر الفصل التالي).

### 6.4 إعدادات مهمة في `settings`
```python
settings.set(settings.USE_WORLD_COORDS, True)   # إحداثيات مطلقة
settings.set(settings.WELD_VERTICES, False)      # الحفاظ على تفاصيل الأوجه
settings.set(settings.APPLY_DEFAULT_MATERIALS, False)
```

### 6.5 المعالجة الجماعية السريعة (Iterator)
لو عندك ملف كبير فيه مئات العناصر، معالجة كل عنصر بشكل منفصل بطيئة. الحل هو `ifcopenshell.geom.iterator`:
```python
iterator = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count())
if iterator.initialize():
    while True:
        shape = iterator.get()
        # معالجة shape
        if not iterator.next():
            break
```
> غير ضروري لمشروعك الحالي (نموذج صغير جدًا)، لكن مهم تعرفه لأي تطبيق واقعي أكبر (زي BIMLens نفسه لاحقًا).

---

## الفصل 7: `ifcopenshell.util` — دوال مساعدة جاهزة

هذا الموديول يوفر اختصارات لعمليات شائعة جدًا، ويوفر عليك إعادة اختراع العجلة.

### 7.1 `ifcopenshell.util.element`
```python
import ifcopenshell.util.element as element_util

# جلب كل الـ Property Sets لعنصر معين كـ dict جاهز
psets = element_util.get_psets(wall)

# جلب العناصر المحتواة داخل فراغ (غرفة) معين
contained = element_util.get_container(wall)  # يرجع الطابق الحاوي للعنصر
```

### 7.2 `ifcopenshell.util.placement`
```python
import ifcopenshell.util.placement as placement_util

matrix = placement_util.get_local_placement(wall.ObjectPlacement)
# matrix هي مصفوفة 4x4 تمثل الموقع والدوران المطلق للعنصر
z_position = matrix[2][3]  # الإحداثي Z المطلق — مفيد لحساب ارتفاع حافة النافذة
```

### 7.3 `ifcopenshell.util.shape`
```python
import ifcopenshell.util.shape as shape_util

# حساب حجم/مساحة من shape مستخرج مسبقًا عبر geom
bbox = shape_util.get_bbox(shape.geometry.verts)
```

### 7.4 `ifcopenshell.util.unit`
```python
import ifcopenshell.util.unit as unit_util

# معرفة عامل التحويل لوحدة الطول المستخدمة بالملف (غالبًا مللي أو متر)
length_unit_scale = unit_util.calculate_unit_scale(model)
real_length = raw_value * length_unit_scale
```
> هذا مهم جدًا لمشروعك: إذا الملف مُعرّف بالملليمتر ونسيت التحويل، كل حساباتك للمساحة ستكون خاطئة بمقدار 10^6 مرة.

### 7.5 `ifcopenshell.util.selector`
يسمح بالبحث عن عناصر عبر صياغة شبيهة بـ query string، مفيد لو بنيت أداة عامة لاحقًا:
```python
import ifcopenshell.util.selector as selector_util
results = selector_util.filter_elements(model, "IfcWall, material=Concrete")
```

---

## الفصل 8: العلاقات (Relationships) — الأهم لفهم "البناء ككائن مترابط"

| العلاقة | الوظيفة |
|---|---|
| `IfcRelAggregates` | تجميع هرمي (مبنى يحوي طوابق، طابق يحوي فراغات) |
| `IfcRelContainedInSpatialStructure` | ربط عنصر (جدار، أثاث) بموقعه المكاني (الطابق) |
| `IfcRelFillsElement` | ربط نافذة/باب بالفتحة التي تملأها داخل الجدار |
| `IfcRelVoidsElement` | ربط الفتحة (Opening) بالجدار الذي فُتحت فيه |
| `IfcRelSpaceBoundary` | تحديد الحدود الفيزيائية للفراغ (أي الجدران تحده) |
| `IfcRelDefinesByProperties` | ربط عنصر بمجموعة خصائصه (Pset) |
| `IfcRelDefinesByType` | ربط عنصر بنوعه العام (مثل نوع نافذة قياسي) |

### مثال عملي: إيجاد النافذة الموجودة داخل جدار معين
```python
for opening_rel in wall.HasOpenings:  # IfcRelVoidsElement
    opening = opening_rel.RelatedOpeningElement
    for fill_rel in opening.HasFillings:  # IfcRelFillsElement
        window = fill_rel.RelatedBuildingElement
        print(window.Name)
```

### مثال: إيجاد كل العناصر داخل غرفة معينة
```python
for rel in model.by_type("IfcRelContainedInSpatialStructure"):
    if rel.RelatingStructure == my_space:
        for elem in rel.RelatedElements:
            print(elem.is_a(), elem.Name)
```

---

## الفصل 9: التحقق من صحة الملف — `ifcopenshell.validate`

قبل ما تعتمد على نموذج IFC ولّدته بنفسك، من الجيد التحقق أنه سليم بنيويًا:
```python
import ifcopenshell.validate

logger = ifcopenshell.validate.json_logger()
ifcopenshell.validate.validate(model, logger)
print(logger.statements)  # قائمة بأي أخطاء أو تحذيرات بنيوية
```
مفيد جدًا في مرحلة الاختبار (Automated Tests) بمشروعك للتأكد أن الملف الذي ولّدته سليم قبل تحليله.

---

## الفصل 10: `ifcopenshell.template` — بداية سريعة

```python
import ifcopenshell.template

model = ifcopenshell.template.create("IFC4",
    project_name="Compliance Test Project")
```
يعطيك مشروعًا فارغًا فيه `IfcProject`، `IfcSite`، `IfcBuilding`، ووحدات قياس افتراضية جاهزة — نقطة انطلاق سريعة بدل بناء كل شيء يدويًا من الصفر.

---

## الفصل 11: أخطاء شائعة يقع فيها المبتدئون

1. **نسيان تحويل الوحدات** — النتائج قد تظهر بمقياس خاطئ تمامًا (متر مقابل ملليمتر).
2. **استخدام Local Coordinates بدل World Coordinates** عند حساب المواقع المطلقة (مثل ارتفاع النافذة عن الأرضية الفعلية).
3. **حذف عنصر مباشرة بدون تنظيف علاقاته** → يترك الملف بحالة غير متسقة.
4. **الخلط بين `IfcOpeningElement` و `IfcWindow`** — النافذة نفسها لا "تحفر" بالجدار، الفتحة هي التي تفعل ذلك، والنافذة "تملأ" الفتحة.
5. **افتراض وجود Quantity Sets جاهزة دائمًا** — ليست كل الملفات تحتوي مساحات محسوبة مسبقًا؛ أحيانًا لازم تحسبها بنفسك من الهندسة.
6. **عدم التحقق من نوع الفراغ (IfcSpace) قبل الافتراض أنه "غرفة داخلية مغلقة"** — قد يمثل IfcSpace مساحة خارجية أو غير مسورة بالكامل.

---

## الفصل 12: تطبيق مباشر على مشروعك (Compliance Checker)

خطوات استخراج البيانات الثلاث المطلوبة بالتاسك، مختصرة كخارطة تنفيذ:

**أ. مساحة الغرفة الداخلية:**
```python
space = model.by_type("IfcSpace")[0]
shape = ifcopenshell.geom.create_shape(settings, space)
# احسب مساحة مضلع الأرضية من verts (أو استخدم Qto_SpaceBaseQuantities إن وُجدت)
```

**ب. مساحة النافذة:**
```python
window = model.by_type("IfcWindow")[0]
# غالبًا OverallWidth و OverallHeight متوفرة كـ Attributes مباشرة
area = window.OverallWidth * window.OverallHeight  # بعد تحويل الوحدات
```

**ج. ارتفاع حافة النافذة عن الأرضية:**
```python
window_matrix = placement_util.get_local_placement(window.ObjectPlacement)
floor_matrix  = placement_util.get_local_placement(storey.ObjectPlacement)

sill_height = window_matrix[2][3] - floor_matrix[2][3]
```

هذه القيم الثلاث هي بالضبط ما يحتاجه منطق التحقق الحتمي (Deterministic Validation) في تاسكك، بمعزل تمامًا عن أي LLM.

---

## الفصل 13: مصادر إضافية للتعمق

- **التوثيق الرسمي**: docs.ifcopenshell.org — فيه الدليل الكامل ووصف كل دالة.
- **مستودع GitHub الرسمي**: يحتوي مجلد `src/ifcopenshell-python/ifcopenshell/api` — أفضل طريقة لفهم كل دالة API هي قراءة كودها المصدري مباشرة (بسيط ومختصر عادة).
- **Bonsai (BlenderBIM)**: مبني بالكامل على هذه المكتبة، ومصدره المفتوح كنز من الأمثلة العملية الواقعية.
- **قناة IFC.js / community forums**: نقاشات لحالات استخدام مشابهة لمشروعك.

---

بهذا يكون عندك تصور شامل عن المكتبة من الأساسيات الهيكلية إلى التطبيق العملي المباشر على متطلبات التاسك. الخطوة التالية المنطقية هي البدء الفعلي بكتابة `ifc_generator.py`.