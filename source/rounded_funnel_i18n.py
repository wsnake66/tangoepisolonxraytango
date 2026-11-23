"""Complete UI vocabulary for the slip-casting funnel selector and settings."""
KEYS = (
    'Funnel Style', 'Contact Diameter', 'Opening Diameter', 'Height Above Model',
    'Placement', 'Number of Funnels', 'Adapted', 'Rounded', 'Automatic',
    'Custom Count', 'Choose a Funnel Style',
    'Choose adapted or rounded slip-casting funnels',
    'Follow the detected surface',
    'Tapered circular funnels on top of the master',
    'Diameter of the lower face where the funnel meets the model',
    'Upper opening diameter; must exceed the contact diameter',
    'Height above the highest point of the model',
    'Choose the funnel count automatically',
    'Use the requested funnel count',
    'Total number of funnels to place',
    'Opening diameter must exceed contact diameter',
)
_ROWS = {
'ES': '''Estilo de embudo|Diámetro de contacto|Diámetro de abertura|Altura sobre el modelo|Colocación|Número de embudos|Adaptado|Redondo|Uno por isla|Cantidad personalizada|Elegir estilo de embudo|Elige embudos adaptados o redondos para colada de barbotina|Sigue la forma de la isla detectada|Embudos circulares cónicos sobre el modelo maestro|Diámetro de la cara inferior donde el embudo toca el modelo|Diámetro de la abertura superior; debe superar el diámetro de contacto|Altura sobre el punto más alto del modelo|Un embudo por isla|Primero las islas más grandes, luego los adicionales a distancias uniformes|Número total de embudos que colocar|El diámetro de abertura debe superar el de contacto''',
'PT': '''Estilo do funil|Diâmetro de contacto|Diâmetro da abertura|Altura acima do modelo|Posicionamento|Número de funis|Adaptado|Redondo|Um por ilha|Quantidade personalizada|Escolher estilo do funil|Escolha funis adaptados ou redondos para colagem de barbotina|Segue a forma da ilha detetada|Funis circulares cónicos no topo do modelo mestre|Diâmetro da face inferior onde o funil toca no modelo|Diâmetro da abertura superior; deve exceder o diâmetro de contacto|Altura acima do ponto mais alto do modelo|Um funil por ilha|Primeiro as ilhas maiores, depois os funis adicionais com espaçamento uniforme|Número total de funis a colocar|O diâmetro da abertura deve exceder o de contacto''',
'PT_BR': '''Estilo do funil|Diâmetro de contato|Diâmetro da abertura|Altura acima do modelo|Posicionamento|Número de funis|Adaptado|Redondo|Um por ilha|Quantidade personalizada|Escolher estilo do funil|Escolha funis adaptados ou redondos para colagem de barbotina|Segue a forma da ilha detectada|Funis circulares cônicos no topo do modelo mestre|Diâmetro da face inferior onde o funil toca o modelo|Diâmetro da abertura superior; deve exceder o diâmetro de contato|Altura acima do ponto mais alto do modelo|Um funil por ilha|Primeiro as ilhas maiores, depois os funis adicionais com espaçamento uniforme|Número total de funis a colocar|O diâmetro da abertura deve exceder o de contato''',
'DE': '''Trichterform|Kontaktdurchmesser|Öffnungsdurchmesser|Höhe über dem Modell|Platzierung|Anzahl der Trichter|Angepasst|Rund|Einer pro Insel|Eigene Anzahl|Trichterform wählen|Angepasste oder runde Trichter für den Schlickerguss wählen|Der Form der erkannten Insel folgen|Konische runde Trichter auf dem Urmodell|Durchmesser der unteren Fläche, an der der Trichter das Modell berührt|Durchmesser der oberen Öffnung; muss größer als der Kontaktdurchmesser sein|Höhe über dem höchsten Punkt des Modells|Ein Trichter pro Insel|Zuerst die größten Inseln, dann gleichmäßig verteilte zusätzliche Trichter|Gesamtzahl der zu platzierenden Trichter|Der Öffnungsdurchmesser muss größer als der Kontaktdurchmesser sein''',
'FR': '''Forme de l’entonnoir|Diamètre de contact|Diamètre d’ouverture|Hauteur au-dessus du modèle|Placement|Nombre d’entonnoirs|Adapté|Rond|Un par îlot|Nombre personnalisé|Choisir la forme de l’entonnoir|Choisir des entonnoirs adaptés ou ronds pour le coulage en barbotine|Suit la forme de l’îlot détecté|Entonnoirs circulaires coniques au-dessus du modèle maître|Diamètre de la face inférieure où l’entonnoir touche le modèle|Diamètre de l’ouverture supérieure ; doit dépasser le diamètre de contact|Hauteur au-dessus du point le plus haut du modèle|Un entonnoir par îlot|Les plus grands îlots d’abord, puis les entonnoirs supplémentaires à intervalles réguliers|Nombre total d’entonnoirs à placer|Le diamètre d’ouverture doit dépasser le diamètre de contact''',
'IT': '''Forma dell’imbuto|Diametro di contatto|Diametro dell’apertura|Altezza sopra il modello|Posizionamento|Numero di imbuti|Adattato|Rotondo|Uno per isola|Quantità personalizzata|Scegli la forma dell’imbuto|Scegli imbuti adattati o rotondi per il colaggio in barbottina|Segue la forma dell’isola rilevata|Imbuti circolari conici sopra il modello maestro|Diametro della faccia inferiore in cui l’imbuto tocca il modello|Diametro dell’apertura superiore; deve superare il diametro di contatto|Altezza sopra il punto più alto del modello|Un imbuto per isola|Prima le isole più grandi, poi gli imbuti aggiuntivi a intervalli regolari|Numero totale di imbuti da posizionare|Il diametro dell’apertura deve superare quello di contatto''',
'TR': '''Huni biçimi|Temas çapı|Ağız çapı|Model üzerindeki yükseklik|Yerleşim|Huni sayısı|Uyarlanmış|Yuvarlak|Ada başına bir|Özel sayı|Huni biçimini seç|Çamur dökümü için uyarlanmış veya yuvarlak huniler seçin|Algılanan adanın şeklini izler|Ana modelin üstünde konik dairesel huniler|Huninin modele temas ettiği alt yüzeyin çapı|Üst ağız çapı; temas çapından büyük olmalıdır|Modelin en yüksek noktasının üzerindeki yükseklik|Ada başına bir huni|Önce en büyük adalar, ardından eşit aralıklı ek huniler|Yerleştirilecek toplam huni sayısı|Ağız çapı temas çapından büyük olmalıdır''',
'RU': '''Форма воронки|Диаметр контакта|Диаметр отверстия|Высота над моделью|Размещение|Количество воронок|Адаптированная|Круглая|Одна на островок|Заданное количество|Выбрать форму воронки|Выберите адаптированные или круглые воронки для шликерного литья|Повторяет форму обнаруженного островка|Круглые конические воронки сверху мастер-модели|Диаметр нижней грани в месте контакта воронки с моделью|Диаметр верхнего отверстия; должен превышать диаметр контакта|Высота над самой высокой точкой модели|Одна воронка на островок|Сначала самые большие островки, затем дополнительные воронки с равными интервалами|Общее количество размещаемых воронок|Диаметр отверстия должен превышать диаметр контакта''',
'JA': '''漏斗の形状|接触面の直径|開口部の直径|モデル上端からの高さ|配置|漏斗の数|形状に適合|円形|各アイランドに1個|個数を指定|漏斗の形状を選択|泥漿鋳込み用に形状適合型または円形の漏斗を選択|検出したアイランドの形状に合わせる|原型の上部に配置する円錐台形の漏斗|漏斗がモデルに接する底面の直径|上部開口の直径。接触面の直径より大きくしてください|モデルの最も高い点から上への高さ|各アイランドに漏斗を1個配置|大きいアイランドから順に配置し、余分な漏斗は等間隔に配置|配置する漏斗の総数|開口部の直径は接触面の直径より大きくしてください''',
'KO': '''깔때기 형태|접촉면 지름|입구 지름|모델 위 높이|배치|깔때기 수|형상 맞춤|원형|아일랜드당 하나|개수 지정|깔때기 형태 선택|슬립 캐스팅용 형상 맞춤 또는 원형 깔때기를 선택하세요|감지된 아일랜드의 형상을 따릅니다|원형 모델 위에 배치하는 원뿔대형 깔때기|깔때기가 모델에 닿는 바닥면의 지름|위쪽 입구의 지름이며 접촉면 지름보다 커야 합니다|모델의 가장 높은 지점 위로 연장되는 높이|아일랜드당 깔때기 하나|가장 큰 아일랜드부터 배치한 후 나머지를 균일한 간격으로 배치|배치할 깔때기의 총개수|입구 지름은 접촉면 지름보다 커야 합니다''',
'ZH': '''漏斗样式|接触面直径|开口直径|高出模型的高度|放置方式|漏斗数量|自适应|圆形|每个孤岛一个|自定义数量|选择漏斗样式|选择用于泥浆浇注的自适应或圆形漏斗|沿用检测到的孤岛形状|位于母模顶部的圆台形漏斗|漏斗与模型接触处的底面直径|顶部开口直径，必须大于接触面直径|高于模型最高点的距离|每个孤岛放置一个漏斗|优先放置在最大的孤岛上，再均匀分布其余漏斗|要放置的漏斗总数|开口直径必须大于接触面直径''',
'AR': '''شكل القمع|قطر التلامس|قطر الفتحة|الارتفاع فوق النموذج|الموضع|عدد الأقماع|متكيف|دائري|واحد لكل جزيرة|عدد مخصص|اختر شكل القمع|اختر أقماعًا متكيفة أو دائرية للصب بالطينة السائلة|يتبع شكل الجزيرة المكتشفة|أقماع دائرية مخروطية أعلى النموذج الأصلي|قطر الوجه السفلي حيث يلامس القمع النموذج|قطر الفتحة العلوية؛ يجب أن يكون أكبر من قطر التلامس|الارتفاع فوق أعلى نقطة في النموذج|قمع واحد لكل جزيرة|الجزر الأكبر أولًا، ثم الأقماع الإضافية على مسافات متساوية|العدد الإجمالي للأقماع المراد وضعها|يجب أن يكون قطر الفتحة أكبر من قطر التلامس''',
}
TRANSLATIONS = {language: dict(zip(KEYS, row.split('|'), strict=True)) for language, row in _ROWS.items()}

# Shared slip-casting settings and development controls introduced with funnels.
_EXTRA_KEYS = (
    'Clear Undercuts (Slip Cast)', 'Diameter', 'Generate Foot', 'Show Master Undercuts',
    'Outer shape used for the Slip Casting box', 'Mold Shape',
    'Generate a foot together with the funnels',
    'For Slip Cast, clear the master when generating the mold; the box always has its undercuts cleared. For other molds, clear the mold box relative to the split direction to improve demolding.',
    'Vertical Faces', 'Reset Clearance Debug', 'Opening',
    'Number of main vertical sides of the box, before beveling', 'Master Base',
    'Run Prepare Casting before generating the mold.',
    'Show Funnel Placement', 'Clearance Debug — Temporary Copy',
)
_EXTRA_ROWS = {
'ES': 'Eliminar contrasalidas (barbotina)|Diámetro|Generar pie|Mostrar contrasalidas del maestro|Forma exterior de la caja para colada de barbotina|Forma del molde|Generar un pie junto con los embudos|En colada de barbotina, elimina las contrasalidas del maestro al generar el molde; las de la caja se eliminan siempre. En otros moldes, elimina las contrasalidas de la caja según la dirección de separación para facilitar el desmoldeo.|Caras verticales|Reiniciar depuración de contrasalidas|Abertura|Número de caras verticales principales de la caja antes del biselado|Base del maestro|Ejecuta Preparar colada antes de generar el molde.|Mostrar islas y colocación de embudos|Depuración de contrasalidas — Copia temporal',
'PT': 'Eliminar reentrâncias (barbotina)|Diâmetro|Gerar pé|Mostrar reentrâncias do mestre|Forma exterior da caixa para colagem de barbotina|Forma do molde|Gerar um pé juntamente com os funis|Na colagem de barbotina, elimina as reentrâncias do mestre ao gerar o molde; as da caixa são sempre eliminadas. Nos outros moldes, elimina as reentrâncias da caixa segundo a direção de separação para facilitar a desmoldagem.|Faces verticais|Reiniciar diagnóstico de reentrâncias|Abertura|Número de faces verticais principais da caixa antes do biselamento|Base do mestre|Execute Preparar colagem antes de gerar o molde.|Mostrar ilhas e posicionamento dos funis|Diagnóstico de reentrâncias — Cópia temporária',
'PT_BR': 'Eliminar reentrâncias (barbotina)|Diâmetro|Gerar pé|Mostrar reentrâncias do mestre|Forma externa da caixa para colagem de barbotina|Forma do molde|Gerar um pé junto com os funis|Na colagem de barbotina, elimina as reentrâncias do mestre ao gerar o molde; as da caixa são sempre eliminadas. Nos outros moldes, elimina as reentrâncias da caixa conforme a direção de separação para facilitar a desmoldagem.|Faces verticais|Reiniciar diagnóstico de reentrâncias|Abertura|Número de faces verticais principais da caixa antes do chanfro|Base do mestre|Execute Preparar colagem antes de gerar o molde.|Mostrar ilhas e posicionamento dos funis|Diagnóstico de reentrâncias — Cópia temporária',
'DE': 'Hinterschneidungen entfernen (Schlickerguss)|Durchmesser|Fuß erzeugen|Hinterschneidungen des Urmodells anzeigen|Außenform des Formkastens für den Schlickerguss|Formkastenform|Einen Fuß zusammen mit den Trichtern erzeugen|Beim Schlickerguss werden die Hinterschneidungen des Urmodells beim Erzeugen der Form entfernt; die des Formkastens werden immer entfernt. Bei anderen Formen werden die Hinterschneidungen des Formkastens entlang der Trennrichtung entfernt, um das Entformen zu erleichtern.|Senkrechte Flächen|Hinterschneidungsdiagnose zurücksetzen|Öffnung|Anzahl der senkrechten Hauptflächen des Formkastens vor dem Abschrägen|Urmodellbasis|Vor dem Erzeugen der Form zuerst Guss vorbereiten ausführen.|Trichterinseln und Platzierung anzeigen|Hinterschneidungsdiagnose — Temporäre Kopie',
'FR': 'Supprimer les contre-dépouilles (barbotine)|Diamètre|Générer un pied|Afficher les contre-dépouilles du modèle maître|Forme extérieure du coffrage pour le coulage en barbotine|Forme du moule|Générer un pied avec les entonnoirs|Pour la barbotine, supprime les contre-dépouilles du modèle maître lors de la génération du moule ; celles du coffrage sont toujours supprimées. Pour les autres moules, supprime les contre-dépouilles du coffrage selon la direction de séparation pour faciliter le démoulage.|Faces verticales|Réinitialiser le diagnostic des contre-dépouilles|Ouverture|Nombre de faces verticales principales du coffrage avant chanfreinage|Base du modèle maître|Exécutez Préparer le coulage avant de générer le moule.|Afficher les îlots et le placement des entonnoirs|Diagnostic des contre-dépouilles — Copie temporaire',
'IT': 'Elimina sottosquadri (barbottina)|Diametro|Genera piede|Mostra sottosquadri del modello master|Forma esterna della cassa per colaggio in barbottina|Forma dello stampo|Genera un piede insieme agli imbuti|Per il colaggio in barbottina, elimina i sottosquadri del master durante la generazione dello stampo; quelli della cassa vengono sempre eliminati. Per gli altri stampi, elimina i sottosquadri della cassa secondo la direzione di divisione per facilitare la sformatura.|Facce verticali|Reimposta diagnostica sottosquadri|Apertura|Numero di facce verticali principali della cassa prima della smussatura|Base del master|Esegui Prepara colaggio prima di generare lo stampo.|Mostra isole e posizionamento degli imbuti|Diagnostica sottosquadri — Copia temporanea',
'TR': 'Ters açıları temizle (çamur dökümü)|Çap|Ayak oluştur|Ana modelin ters açılarını göster|Çamur dökümü kalıp kutusunun dış şekli|Kalıp şekli|Hunilerle birlikte bir ayak oluştur|Çamur dökümünde kalıp oluşturulurken ana modelin ters açıları temizlenir; kutunun ters açıları her zaman temizlenir. Diğer kalıplarda, kalıptan çıkarmayı kolaylaştırmak için kutunun ters açıları ayırma yönüne göre temizlenir.|Dikey yüzler|Ters açı hata ayıklamasını sıfırla|Açıklık|Pah kırmadan önce kutunun ana dikey yüzlerinin sayısı|Ana model tabanı|Kalıbı oluşturmadan önce Dökümü hazırla işlemini çalıştırın.|Huni adalarını ve yerleşimini göster|Ters açı hata ayıklama — Geçici kopya',
'RU': 'Устранить поднутрения (шликерное литьё)|Диаметр|Создать ножку|Показать поднутрения мастер-модели|Внешняя форма опоки для шликерного литья|Форма опоки|Создать ножку вместе с воронками|При шликерном литье поднутрения мастер-модели устраняются при создании формы; поднутрения опоки устраняются всегда. Для других форм поднутрения опоки устраняются относительно направления разъёма для облегчения извлечения.|Вертикальные грани|Сбросить отладку поднутрений|Открытая сторона|Количество основных вертикальных граней опоки до снятия фасок|Основание мастер-модели|Перед созданием формы выполните подготовку литья.|Показать островки и расположение воронок|Отладка поднутрений — Временная копия',
'JA': 'アンダーカットを除去（泥漿鋳込み）|直径|高台を生成|原型のアンダーカットを表示|泥漿鋳込み用型枠の外形|型枠の形状|漏斗とともに高台を生成|泥漿鋳込みでは型の生成時に原型のアンダーカットを除去します。型枠のアンダーカットは常に除去されます。他の型では、型抜きを容易にするため分割方向に応じて型枠のアンダーカットを除去します。|垂直面|アンダーカットのデバッグをリセット|開口部|面取り前の型枠の主な垂直面の数|原型の台座|型を生成する前に鋳込み準備を実行してください。|漏斗のアイランドと配置を表示|アンダーカットのデバッグ — 一時コピー',
'KO': '언더컷 제거 (슬립 캐스팅)|지름|굽 생성|원형 모델의 언더컷 표시|슬립 캐스팅 몰드 박스의 외형|몰드 형태|깔때기와 함께 굽 생성|슬립 캐스팅에서는 몰드 생성 시 원형 모델의 언더컷을 제거하며, 박스의 언더컷은 항상 제거합니다. 다른 몰드에서는 탈형을 쉽게 하도록 분할 방향에 따라 몰드 박스의 언더컷을 제거합니다.|수직 면|언더컷 디버깅 초기화|개구부|모서리를 다듬기 전 박스의 주요 수직 면 수|원형 모델 베이스|몰드를 생성하기 전에 캐스팅 준비를 실행하세요.|깔때기 아일랜드 및 배치 표시|언더컷 디버깅 — 임시 복사본',
'ZH': '清除倒扣（泥浆浇注）|直径|生成底足|显示母模倒扣|泥浆浇注模盒的外部形状|模具形状|与漏斗一起生成底足|泥浆浇注时，在生成模具时清除母模倒扣；模盒倒扣始终会被清除。对于其他模具，按分模方向清除模盒倒扣以便脱模。|竖直面|重置倒扣调试|开口|倒角前模盒的主要竖直面数量|母模底座|生成模具前请先运行浇注准备。|显示漏斗孤岛和放置位置|倒扣调试 — 临时副本',
'AR': 'إزالة التعشيقات العكسية (صب الطينة)|القطر|إنشاء قدم|إظهار التعشيقات العكسية للنموذج الأصلي|الشكل الخارجي لصندوق قالب صب الطينة|شكل القالب|إنشاء قدم مع الأقماع|في صب الطينة، تزال التعشيقات العكسية للنموذج الأصلي عند إنشاء القالب؛ وتزال تعشيقات الصندوق دائمًا. في القوالب الأخرى، تزال تعشيقات صندوق القالب وفق اتجاه الفصل لتسهيل إخراج القطعة.|الأوجه الرأسية|إعادة ضبط تصحيح التعشيقات العكسية|الفتحة|عدد الأوجه الرأسية الرئيسية للصندوق قبل شطف الحواف|قاعدة النموذج الأصلي|شغّل تحضير الصب قبل إنشاء القالب.|إظهار الجزر ومواضع الأقماع|تصحيح التعشيقات العكسية — نسخة مؤقتة',
}
for _language, _row in _EXTRA_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_EXTRA_KEYS, _row.split('|'), strict=True)))

_ADAPTED_KEYS = ('Adapted Variant', 'External · Horizontal Trim', 'Expanded funnel for horizontal trimming',
                 'Internal · Vertical Trim', 'Zero-offset funnel with outward-only clearance for vertical trimming')
_ADAPTED_ROWS = {
'ES': 'Variante adaptada|Externo · Corte horizontal|Embudo expandido para corte horizontal|Interno · Corte vertical|Embudo sin desplazamiento con despeje solo hacia fuera para corte vertical',
'PT': 'Variante adaptada|Externo · Corte horizontal|Funil expandido para corte horizontal|Interno · Corte vertical|Funil sem afastamento com desimpedimento apenas para fora para corte vertical',
'PT_BR': 'Variante adaptada|Externo · Corte horizontal|Funil expandido para corte horizontal|Interno · Corte vertical|Funil sem afastamento com liberação apenas para fora para corte vertical',
'DE': 'Angepasste Variante|Außen · Horizontaler Schnitt|Erweiterter Trichter für horizontales Abschneiden|Innen · Vertikaler Schnitt|Trichter ohne Versatz mit Freistellung nur nach außen für vertikales Abschneiden',
'FR': 'Variante adaptée|Externe · Coupe horizontale|Entonnoir élargi pour une coupe horizontale|Interne · Coupe verticale|Entonnoir sans décalage avec dégagement uniquement vers l’extérieur pour une coupe verticale',
'IT': 'Variante adattata|Esterno · Taglio orizzontale|Imbuto espanso per il taglio orizzontale|Interno · Taglio verticale|Imbuto senza offset con svuotamento solo verso l’esterno per il taglio verticale',
'TR': 'Uyarlanmış varyant|Dış · Yatay kesim|Yatay kesim için genişletilmiş huni|İç · Dikey kesim|Dikey kesim için yalnızca dışa doğru boşaltılan, ofsetsiz huni',
'RU': 'Адаптированный вариант|Внешний · Горизонтальный срез|Расширенная воронка для горизонтального среза|Внутренний · Вертикальный срез|Воронка без смещения с устранением поднутрений только наружу для вертикального среза',
'JA': '形状適合型の種類|外側 · 水平カット|水平カット用に拡張した漏斗|内側 · 垂直カット|垂直カット用のオフセットなしの漏斗。外向きのみアンダーカットを除去します',
'KO': '형상 맞춤 유형|외부 · 수평 절단|수평 절단용으로 확장한 깔때기|내부 · 수직 절단|수직 절단용 오프셋 없는 깔때기. 바깥쪽으로만 언더컷을 제거합니다',
'ZH': '自适应类型|外部 · 水平切割|用于水平切割的扩展漏斗|内部 · 垂直切割|用于垂直切割的零偏移漏斗，仅向外清除倒扣',
'AR': 'نوع القمع المتكيف|خارجي · قطع أفقي|قمع موسع للقطع الأفقي|داخلي · قطع رأسي|قمع دون إزاحة مع إزالة التعشيقات نحو الخارج فقط للقطع الرأسي',
}
for _language, _row in _ADAPTED_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_ADAPTED_KEYS, _row.split('|'), strict=True)))

_DETECTION_KEYS = ('Detection Detail', 'Controls how much surface detail is retained', 'Low', 'Retain less surface detail', 'Medium', 'Retain a balanced amount of surface detail', 'High', 'Retain more surface detail')
_DETECTION_ROWS = {
'ES': 'Detección de islas|Controla cuánto se agrupan las islas cercanas|Baja|Distancia de agrupación alta y área mínima de isla alta|Media|Distancia de agrupación media y área mínima de isla media|Alta|Distancia de agrupación baja y área mínima de isla baja',
'PT': 'Deteção de ilhas|Controla o agrupamento de ilhas próximas|Baixa|Distância de agrupamento alta e área mínima de ilha alta|Média|Distância de agrupamento média e área mínima de ilha média|Alta|Distância de agrupamento baixa e área mínima de ilha baixa',
'PT_BR': 'Detecção de ilhas|Controla o agrupamento de ilhas próximas|Baixa|Distância de agrupamento alta e área mínima de ilha alta|Média|Distância de agrupamento média e área mínima de ilha média|Alta|Distância de agrupamento baixa e área mínima de ilha baixa',
'DE': 'Inselerkennung|Bestimmt, wie stark benachbarte Inseln zusammengefasst werden|Niedrig|Großer Gruppierungsabstand und große Mindestinselfläche|Mittel|Mittlerer Gruppierungsabstand und mittlere Mindestinselfläche|Hoch|Kleiner Gruppierungsabstand und kleine Mindestinselfläche',
'FR': 'Détection des îlots|Contrôle le regroupement des îlots proches|Faible|Distance de regroupement et aire minimale des îlots élevées|Moyen|Distance de regroupement et aire minimale des îlots moyennes|Élevé|Distance de regroupement et aire minimale des îlots faibles',
'IT': 'Rilevamento delle isole|Controlla quanto vengono raggruppate le isole vicine|Basso|Distanza di raggruppamento e area minima delle isole elevate|Medio|Distanza di raggruppamento e area minima delle isole medie|Alto|Distanza di raggruppamento e area minima delle isole ridotte',
'TR': 'Ada algılama|Yakın adaların ne ölçüde gruplandırılacağını belirler|Düşük|Yüksek gruplama mesafesi ve yüksek minimum ada alanı|Orta|Orta gruplama mesafesi ve orta minimum ada alanı|Yüksek|Düşük gruplama mesafesi ve düşük minimum ada alanı',
'RU': 'Обнаружение островков|Определяет степень объединения соседних островков|Низкий|Большое расстояние объединения и большая минимальная площадь островка|Средний|Среднее расстояние объединения и средняя минимальная площадь островка|Высокий|Малое расстояние объединения и малая минимальная площадь островка',
'JA': 'アイランド検出|近接するアイランドをまとめる強さを設定します|低|グループ化距離とアイランドの最小面積を大きくします|中|グループ化距離とアイランドの最小面積を中程度にします|高|グループ化距離とアイランドの最小面積を小さくします',
'KO': '아일랜드 감지|인접한 아일랜드를 묶는 정도를 조절합니다|낮음|큰 그룹화 거리와 큰 최소 아일랜드 면적|중간|중간 그룹화 거리와 중간 최소 아일랜드 면적|높음|작은 그룹화 거리와 작은 최소 아일랜드 면적',
'ZH': '孤岛检测|控制相邻孤岛的合并程度|低|较大的合并距离和孤岛最小面积|中|中等的合并距离和孤岛最小面积|高|较小的合并距离和孤岛最小面积',
'AR': 'اكتشاف الجزر|التحكم في مدى تجميع الجزر المتقاربة|منخفض|مسافة تجميع كبيرة وحد أدنى كبير لمساحة الجزيرة|متوسط|مسافة تجميع متوسطة وحد أدنى متوسط لمساحة الجزيرة|مرتفع|مسافة تجميع صغيرة وحد أدنى صغير لمساحة الجزيرة',
}
for _language, _row in _DETECTION_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_DETECTION_KEYS, _row.split('|'), strict=True)))

_INTERNAL_MODEL_KEYS = (
    'Model Type', 'Hollow Model', 'Solid Model',
    'Model with a cavity',
    'Solid model',
)
_INTERNAL_MODEL_ROWS = {
'ES': 'Tipo de modelo|Modelo hueco|Modelo macizo|Modelo con cavidad; conserva la forma actual de la isla|Extrae islas grandes y planas, las extiende y remalla',
'PT': 'Tipo de modelo|Modelo oco|Modelo maciço|Modelo com cavidade; preserva a forma atual da ilha|Extrai ilhas grandes e planas, prolonga e refaz a malha',
'PT_BR': 'Tipo de modelo|Modelo oco|Modelo maciço|Modelo com cavidade; preserva a forma atual da ilha|Extrai ilhas grandes e planas, estende e refaz a malha',
'DE': 'Modelltyp|Hohles Modell|Massives Modell|Modell mit Hohlraum; behält die aktuelle Inselform bei|Extrahiert große flache Inseln, verlängert sie und vernetzt sie neu',
'FR': 'Type de modèle|Modèle creux|Modèle plein|Modèle avec cavité ; conserve la forme actuelle de l’îlot|Extrait de grands îlots plats, les prolonge et recrée le maillage',
'IT': 'Tipo di modello|Modello cavo|Modello pieno|Modello con cavità; conserva la forma attuale dell’isola|Estrae grandi isole piatte, le estende e ricrea la mesh',
'TR': 'Model türü|İçi boş model|Dolu model|Boşluk içeren model; mevcut ada şeklini korur|Büyük düz adaları çıkarır, uzatır ve yeniden ağ oluşturur',
'RU': 'Тип модели|Полая модель|Сплошная модель|Модель с полостью; сохраняет текущую форму островка|Извлекает крупные плоские островки, удлиняет и перестраивает сетку',
'JA': 'モデルの種類|中空モデル|中実モデル|空洞のあるモデル。現在のアイランド形状を保持します|大きな平坦アイランドを抽出し、延長してリメッシュします',
'KO': '모델 유형|속이 빈 모델|속이 찬 모델|공동이 있는 모델이며 현재 아일랜드 형태를 유지합니다|크고 평평한 아일랜드를 추출하고 연장한 뒤 리메시합니다',
'ZH': '模型类型|空心模型|实心模型|带空腔的模型；保留当前孤岛形状|提取较大的平坦孤岛，延伸并重新网格化',
'AR': 'نوع النموذج|نموذج مجوف|نموذج مصمت|نموذج به تجويف؛ يحافظ على شكل الجزيرة الحالي|استخراج الجزر الكبيرة المسطحة وتمديدها وإعادة تشكيل الشبكة',
}
for _language, _row in _INTERNAL_MODEL_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_INTERNAL_MODEL_KEYS, _row.split('|'), strict=True)))

_INTERNAL_EXPANSION_KEYS = (
    'Funnel Taper',
    'Expand the top of internal adapted funnels by this percentage; zero disables expansion',
)
_INTERNAL_EXPANSION_ROWS = {
'ES': 'Conicidad del embudo|Expande la parte superior de los embudos adaptados internos en este porcentaje; cero desactiva la expansión',
'PT': 'Conicidade do funil|Expande o topo dos funis adaptados internos nesta percentagem; zero desativa a expansão',
'PT_BR': 'Conicidade do funil|Expande o topo dos funis adaptados internos nesta porcentagem; zero desativa a expansão',
'DE': 'Trichterkonizität|Weitet die Oberseite interner angepasster Trichter um diesen Prozentsatz auf; null deaktiviert die Aufweitung',
'FR': 'Conicité de l’entonnoir|Élargit le sommet des entonnoirs adaptés internes de ce pourcentage ; zéro désactive l’élargissement',
'IT': 'Conicità dell’imbuto|Espande la sommità degli imbuti adattati interni di questa percentuale; zero disattiva l’espansione',
'TR': 'Huni konikliği|İç uyarlanmış hunilerin üstünü bu yüzde kadar genişletir; sıfır genişlemeyi devre dışı bırakır',
'RU': 'Конусность воронки|Расширяет верх внутренних адаптированных воронок на указанный процент; ноль отключает расширение',
'JA': 'ファンネルのテーパー|内部適合ファンネルの上部を指定した割合で拡張します。0で拡張を無効にします',
'KO': '깔때기 테이퍼|내부 맞춤형 깔때기의 상단을 지정한 비율로 확장합니다. 0이면 확장하지 않습니다',
'ZH': '漏斗锥度|按此百分比扩展内部适配漏斗的顶部；设为零则禁用扩展',
'AR': 'تدرّج القمع المخروطي|توسيع أعلى الأقماع الداخلية المكيّفة بهذه النسبة؛ الصفر يعطل التوسيع',
}
for _language, _row in _INTERNAL_EXPANSION_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_INTERNAL_EXPANSION_KEYS, _row.split('|'), strict=True)))



_INSET_KEYS = ('Surface Inset', 'Adjust the detected surface boundary')
_INSET_ROWS = {
'ES': 'Retranqueo de islas|Reduce las islas planas hacia dentro en XY sin cambiar su altura',
'PT': 'Recuo das ilhas|Reduz as ilhas planas para dentro em XY sem alterar a altura',
'PT_BR': 'Recuo das ilhas|Reduz as ilhas planas para dentro em XY sem alterar a altura',
'DE': 'Inselversatz nach innen|Verkleinert flache Inseln in XY nach innen, ohne ihre Höhe zu ändern',
'FR': 'Retrait des îlots|Réduit les îlots plats vers l’intérieur en XY sans modifier leur hauteur',
'IT': 'Rientro delle isole|Riduce le isole piatte verso l’interno in XY senza modificarne l’altezza',
'TR': 'Ada içe ofseti|Düz adaları yüksekliklerini değiştirmeden XY düzleminde içe küçültür',
'RU': 'Отступ островков|Уменьшает плоские островки внутрь по XY без изменения высоты',
'JA': 'アイランドのインセット|高さを変えずに平坦なアイランドをXY方向に内側へ縮小します',
'KO': '아일랜드 인셋|높이를 바꾸지 않고 평평한 아일랜드를 XY 방향으로 안쪽으로 줄입니다',
'ZH': '孤岛内缩|在 XY 平面向内收缩平坦孤岛，不改变高度',
'AR': 'إزاحة الجزر للداخل|تقليص الجزر المسطحة للداخل في XY دون تغيير ارتفاعها',
}
for _language, _row in _INSET_ROWS.items():
    TRANSLATIONS[_language].update(dict(zip(_INSET_KEYS, _row.split('|'), strict=True)))

_MODE_KEYS = ('Automatic placement or a custom total',)
for _catalog in TRANSLATIONS.values():
    _catalog.update({key: key for key in _MODE_KEYS})
