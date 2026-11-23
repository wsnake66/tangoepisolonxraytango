"""Translations for image selectors and their associated settings."""

KEYS = (
    "Open Base",
    "Fully Enclosed",
    "One Piece",
    "Per Split",
    "Keep the master seated on the base without a downward wrapper extension",
    "Extend the wrappers and base downward by the mold thickness, leaving the master above the base",
    "Join all master base sections into one piece",
    "Keep one master base per box split section",
    "Keep one master base per box split, with its own side locks and no locking gap",
    "Build one master base or an independent base for each box split section",
    "Choose the multipart base layout",
    "Choose a Master Base",
    "Choose one piece or an independent master base per split section",
    "Choose a Multipart Opening",
    "Choose an open-base or fully enclosed multipart mold",
    "Foot",
    "No Foot",
    "Generate funnels without a foot",
    "Choose a Foot",
    "Choose whether to generate a foot with the funnels",
    "Keep only bands around split planes and the selected ring to save material.",
    "Start the tray wrapper directly from the patron geometry",
    "Contour",
    "Start the tray wrapper from a sphere for a safer outer contour",
    "Use a cube outer shape",
    "Use a cylinder outer shape",
    "Adapt the outer shape to the model",
    "Batch tests completed: {count} test case(s) in {path}",
    "Run All Generators (Defaults)",
    "Run All Multipart Options (6 per Model)",
    "Run All Slip Cast Options (24 per Model)",
)

_ROWS = {
    "ES": (
        "Base abierta|Totalmente cerrado|Una pieza|Por división|Mantener el modelo maestro apoyado en la base sin extender la envolvente hacia abajo|Extender las envolventes y la base hacia abajo según el grosor del molde, dejando el modelo maestro por encima de la base|Unir todas las secciones de la base del modelo maestro en una pieza|Mantener una base del modelo maestro por sección de la caja|Mantener una base del modelo maestro por división de la caja, con sus propios cierres laterales y sin holgura de cierre|Crear una base del modelo maestro o una base independiente para cada sección de la caja|Elegir la disposición de la base del molde multiparte|Elegir una base del modelo maestro|Elegir una pieza o una base del modelo maestro independiente por sección|Elegir una abertura del molde multiparte|Elegir un molde multiparte de base abierta o totalmente cerrado|Pie|Sin pie|Generar embudos sin pie|Elegir un pie|Elegir si se genera un pie junto con los embudos|Conservar solo bandas alrededor de los planos de división y del anillo seleccionado para ahorrar material.|Iniciar la envolvente de la bandeja directamente desde la geometría del patrón|Contorno|Iniciar la envolvente de la bandeja desde una esfera para obtener un contorno exterior más seguro|Usar una forma exterior cúbica|Usar una forma exterior cilíndrica|Adaptar la forma exterior al modelo|Pruebas por lotes completadas: {count} caso(s) de prueba en {path}|Ejecutar todos los generadores (valores predeterminados)|Ejecutar todas las opciones multiparte (6 por modelo)|Ejecutar todas las opciones de colada de barbotina (24 por modelo)"
    ),
    "PT": (
        "Base aberta|Totalmente fechado|Peça única|Por divisão|Manter o modelo mestre apoiado na base sem estender o invólucro para baixo|Estender os invólucros e a base para baixo pela espessura do molde, deixando o modelo mestre acima da base|Unir todas as secções da base do modelo mestre numa peça|Manter uma base do modelo mestre por secção da caixa|Manter uma base do modelo mestre por divisão da caixa, com os seus próprios fechos laterais e sem folga de fecho|Criar uma base do modelo mestre ou uma base independente para cada secção da caixa|Escolher a disposição da base do molde multipartes|Escolher uma base do modelo mestre|Escolher uma peça única ou uma base do modelo mestre independente por secção|Escolher uma abertura do molde multipartes|Escolher um molde multipartes de base aberta ou totalmente fechado|Pé|Sem pé|Gerar funis sem pé|Escolher um pé|Escolher se deve gerar um pé juntamente com os funis|Manter apenas faixas em torno dos planos de divisão e do anel selecionado para poupar material.|Iniciar o invólucro da bandeja diretamente a partir da geometria do padrão|Contorno|Iniciar o invólucro da bandeja a partir de uma esfera para um contorno exterior mais seguro|Usar uma forma exterior cúbica|Usar uma forma exterior cilíndrica|Adaptar a forma exterior ao modelo|Testes em lote concluídos: {count} caso(s) de teste em {path}|Executar todos os geradores (predefinições)|Executar todas as opções multipartes (6 por modelo)|Executar todas as opções de colagem de barbotina (24 por modelo)"
    ),
    "PT_BR": (
        "Base aberta|Totalmente fechado|Peça única|Por divisão|Manter o modelo mestre apoiado na base sem estender o invólucro para baixo|Estender os invólucros e a base para baixo pela espessura do molde, deixando o modelo mestre acima da base|Unir todas as seções da base do modelo mestre em uma peça|Manter uma base do modelo mestre por seção da caixa|Manter uma base do modelo mestre por divisão da caixa, com suas próprias travas laterais e sem folga de travamento|Criar uma base do modelo mestre ou uma base independente para cada seção da caixa|Escolher a disposição da base do molde multipartes|Escolher uma base do modelo mestre|Escolher uma peça única ou uma base do modelo mestre independente por seção|Escolher uma abertura do molde multipartes|Escolher um molde multipartes de base aberta ou totalmente fechado|Pé|Sem pé|Gerar funis sem pé|Escolher um pé|Escolher se deve gerar um pé junto com os funis|Manter apenas faixas ao redor dos planos de divisão e do anel selecionado para economizar material.|Iniciar o invólucro da bandeja diretamente a partir da geometria do padrão|Contorno|Iniciar o invólucro da bandeja a partir de uma esfera para um contorno externo mais seguro|Usar uma forma externa cúbica|Usar uma forma externa cilíndrica|Adaptar a forma externa ao modelo|Testes em lote concluídos: {count} caso(s) de teste em {path}|Executar todos os geradores (padrões)|Executar todas as opções multipartes (6 por modelo)|Executar todas as opções de colagem de barbotina (24 por modelo)"
    ),
    "DE": (
        "Offene Basis|Vollständig geschlossen|Einteilig|Pro Teilung|Das Urmodell auf der Basis belassen, ohne die Hülle nach unten zu verlängern|Hüllen und Basis um die Formdicke nach unten verlängern, sodass das Urmodell oberhalb der Basis bleibt|Alle Abschnitte der Urmodellbasis zu einem Stück verbinden|Eine Urmodellbasis pro Formkastenabschnitt beibehalten|Eine Urmodellbasis pro Formkastenteilung mit eigenen seitlichen Verriegelungen und ohne Verriegelungsspalt beibehalten|Eine Urmodellbasis oder eine unabhängige Basis für jeden Formkastenabschnitt erstellen|Die Basisanordnung der mehrteiligen Form wählen|Eine Urmodellbasis wählen|Eine einteilige oder eine unabhängige Urmodellbasis pro Abschnitt wählen|Eine Öffnung der mehrteiligen Form wählen|Eine mehrteilige Form mit offener Basis oder vollständig geschlossene Form wählen|Fuß|Ohne Fuß|Trichter ohne Fuß erzeugen|Einen Fuß wählen|Wählen, ob zusammen mit den Trichtern ein Fuß erzeugt wird|Nur Bänder um die Trennebenen und den gewählten Ring beibehalten, um Material zu sparen.|Die Tablett-Hülle direkt aus der Modellgeometrie erzeugen|Kontur|Die Tablett-Hülle aus einer Kugel erzeugen, um eine sicherere Außenkontur zu erhalten|Eine würfelförmige Außenform verwenden|Eine zylindrische Außenform verwenden|Die Außenform an das Modell anpassen|Stapeltests abgeschlossen: {count} Testfall/Testfälle in {path}|Alle Generatoren ausführen (Standardwerte)|Alle mehrteiligen Optionen ausführen (6 pro Modell)|Alle Schlickergussoptionen ausführen (24 pro Modell)"
    ),
    "FR": (
        "Base ouverte|Entièrement fermé|Une seule pièce|Par section|Garder le modèle maître posé sur la base sans prolonger l’enveloppe vers le bas|Prolonger les enveloppes et la base vers le bas de l’épaisseur du moule, en laissant le modèle maître au-dessus de la base|Réunir toutes les sections de la base du modèle maître en une seule pièce|Conserver une base du modèle maître par section du coffrage|Conserver une base du modèle maître par section du coffrage, avec ses propres verrouillages latéraux et sans jeu de verrouillage|Créer une base du modèle maître ou une base indépendante pour chaque section du coffrage|Choisir la disposition de la base du moule en plusieurs parties|Choisir une base du modèle maître|Choisir une seule pièce ou une base du modèle maître indépendante par section|Choisir une ouverture du moule en plusieurs parties|Choisir un moule en plusieurs parties à base ouverte ou entièrement fermé|Pied|Sans pied|Générer les entonnoirs sans pied|Choisir un pied|Choisir s’il faut générer un pied avec les entonnoirs|Conserver uniquement les bandes autour des plans de séparation et de l’anneau sélectionné pour économiser du matériau.|Créer l’enveloppe du plateau directement à partir de la géométrie du modèle|Contour|Créer l’enveloppe du plateau à partir d’une sphère pour un contour extérieur plus sûr|Utiliser une forme extérieure cubique|Utiliser une forme extérieure cylindrique|Adapter la forme extérieure au modèle|Tests par lots terminés : {count} cas de test dans {path}|Exécuter tous les générateurs (valeurs par défaut)|Exécuter toutes les options en plusieurs parties (6 par modèle)|Exécuter toutes les options de coulage en barbotine (24 par modèle)"
    ),
    "IT": (
        "Base aperta|Completamente chiuso|Pezzo unico|Per sezione|Mantenere il modello master appoggiato sulla base senza estendere l’involucro verso il basso|Estendere gli involucri e la base verso il basso dello spessore dello stampo, lasciando il modello master sopra la base|Unire tutte le sezioni della base del master in un unico pezzo|Mantenere una base del master per ogni sezione della cassa|Mantenere una base del master per ogni sezione della cassa, con i propri blocchi laterali e senza gioco di bloccaggio|Creare una base del master o una base indipendente per ogni sezione della cassa|Scegliere la disposizione della base dello stampo multiparte|Scegliere una base del master|Scegliere un pezzo unico o una base del master indipendente per ogni sezione|Scegliere un’apertura dello stampo multiparte|Scegliere uno stampo multiparte a base aperta o completamente chiuso|Piede|Senza piede|Generare imbuti senza piede|Scegliere un piede|Scegliere se generare un piede insieme agli imbuti|Mantenere solo le fasce attorno ai piani di divisione e all’anello selezionato per risparmiare materiale.|Creare l’involucro del vassoio direttamente dalla geometria del modello|Contorno|Creare l’involucro del vassoio da una sfera per un contorno esterno più sicuro|Usare una forma esterna cubica|Usare una forma esterna cilindrica|Adattare la forma esterna al modello|Test in batch completati: {count} casi di test in {path}|Eseguire tutti i generatori (valori predefiniti)|Eseguire tutte le opzioni multiparte (6 per modello)|Eseguire tutte le opzioni di colaggio in barbottina (24 per modello)"
    ),
    "TR": (
        "Açık taban|Tamamen kapalı|Tek parça|Bölüm başına|Kılıfı aşağı doğru uzatmadan ana modeli taban üzerinde tut|Kılıfları ve tabanı kalıp kalınlığı kadar aşağı uzatarak ana modeli tabanın üzerinde bırak|Ana model tabanının tüm bölümlerini tek parçada birleştir|Kutu bölümü başına bir ana model tabanı tut|Her kutu bölümü için kendi yan kilitleri olan ve kilit boşluğu olmayan bir ana model tabanı tut|Tek bir ana model tabanı veya her kutu bölümü için bağımsız bir taban oluştur|Çok parçalı kalıbın taban düzenini seç|Ana model tabanı seç|Tek parça veya bölüm başına bağımsız ana model tabanı seç|Çok parçalı kalıp açıklığı seç|Açık tabanlı veya tamamen kapalı çok parçalı kalıp seç|Ayak|Ayaksız|Hunileri ayaksız oluştur|Ayak seç|Hunilerle birlikte ayak oluşturulup oluşturulmayacağını seç|Malzemeden tasarruf etmek için yalnızca ayırma düzlemleri ve seçilen halka etrafındaki şeritleri tut.|Tepsi kılıfını doğrudan model geometrisinden başlat|Kontur|Daha güvenli bir dış kontur için tepsi kılıfını bir küreden başlat|Küp dış şekli kullan|Silindir dış şekli kullan|Dış şekli modele uyarla|Toplu testler tamamlandı: {path} içinde {count} test durumu|Tüm oluşturucuları çalıştır (varsayılanlar)|Tüm çok parçalı seçenekleri çalıştır (model başına 6)|Tüm çamur dökümü seçeneklerini çalıştır (model başına 24)"
    ),
    "RU": (
        "Открытое основание|Полностью закрытая|Цельное|По секциям|Оставить мастер-модель на основании без удлинения оболочки вниз|Удлинить оболочки и основание вниз на толщину формы, оставив мастер-модель над основанием|Объединить все секции основания мастер-модели в одну деталь|Оставить одно основание мастер-модели на каждую секцию опоки|Оставить отдельное основание мастер-модели для каждой секции опоки с собственными боковыми замками и без зазора замков|Создать одно основание мастер-модели или отдельное основание для каждой секции опоки|Выбрать компоновку основания многосоставной формы|Выбрать основание мастер-модели|Выбрать цельное основание мастер-модели или отдельное для каждой секции|Выбрать отверстие многосоставной формы|Выбрать многосоставную форму с открытым основанием или полностью закрытую|Ножка|Без ножки|Создать воронки без ножки|Выбрать ножку|Выбрать, создавать ли ножку вместе с воронками|Оставить только полосы вокруг плоскостей разъёма и выбранного кольца для экономии материала.|Создать оболочку поддона непосредственно из геометрии модели|Контур|Создать оболочку поддона из сферы для более безопасного внешнего контура|Использовать кубическую внешнюю форму|Использовать цилиндрическую внешнюю форму|Адаптировать внешнюю форму к модели|Пакетные тесты завершены: {count} тестов в {path}|Запустить все генераторы (по умолчанию)|Запустить все многосоставные варианты (6 на модель)|Запустить все варианты шликерного литья (24 на модель)"
    ),
    "JA": (
        "底面開放|完全密閉|一体型|分割ごと|外殻を下方に延長せず、原型を台座上に置く|外殻と台座を型の厚さ分だけ下方へ延長し、原型を台座より上に保つ|原型台座の全セクションを一体化する|型枠の分割セクションごとに原型台座を設ける|型枠の分割ごとに独立した側面ロックを持ち、ロック隙間のない原型台座を設ける|原型台座を一体で作成するか、型枠の分割セクションごとに独立して作成する|多分割型の台座構成を選択|原型台座を選択|一体型または分割セクションごとの独立した原型台座を選択|多分割型の開口部を選択|底面開放または完全密閉の多分割型を選択|高台|高台なし|高台なしで漏斗を生成|高台を選択|漏斗とともに高台を生成するか選択|材料を節約するため、分割平面と選択したリングの周囲の帯のみを残す。|パターンの形状から直接トレイの外殻を作成|輪郭|より安全な外周を得るため、球からトレイの外殻を作成|立方体の外形を使用|円柱の外形を使用|外形をモデルに合わせる|バッチテスト完了：{path} に {count} 件のテストケース|すべてのジェネレーターを実行（既定値）|すべての多分割オプションを実行（モデルごとに6件）|すべての泥漿鋳込みオプションを実行（モデルごとに24件）"
    ),
    "KO": (
        "개방형 베이스|완전 밀폐형|일체형|분할별|외피를 아래로 연장하지 않고 원형 모델을 베이스 위에 유지|외피와 베이스를 몰드 두께만큼 아래로 연장하여 원형 모델을 베이스 위에 배치|원형 모델 베이스의 모든 부분을 하나로 결합|박스 분할 구역마다 원형 모델 베이스 하나 유지|각 박스 분할마다 독립적인 측면 잠금장치가 있고 잠금 간격이 없는 원형 모델 베이스 유지|원형 모델 베이스를 하나로 만들거나 박스 분할 구역마다 독립적으로 생성|다분할 몰드의 베이스 구성 선택|원형 모델 베이스 선택|일체형 또는 분할 구역별 독립 원형 모델 베이스 선택|다분할 몰드 개구부 선택|개방형 베이스 또는 완전 밀폐형 다분할 몰드 선택|굽|굽 없음|굽 없이 깔때기 생성|굽 선택|깔때기와 함께 굽을 생성할지 선택|재료를 절약하기 위해 분할 평면과 선택한 링 주변의 띠만 유지합니다.|패턴 형상에서 직접 트레이 외피 생성 시작|윤곽|더 안전한 외부 윤곽을 위해 구에서 트레이 외피 생성 시작|정육면체 외형 사용|원기둥 외형 사용|외형을 모델에 맞춤|일괄 테스트 완료: {path}에 테스트 사례 {count}개|모든 생성기 실행 (기본값)|모든 다분할 옵션 실행 (모델당 6개)|모든 슬립 캐스팅 옵션 실행 (모델당 24개)"
    ),
    "ZH": (
        "开放底座|完全封闭|一体式|按分模区|将母模保持在底座上，不向下延伸外壳|将外壳和底座向下延伸一个模具厚度，使母模位于底座上方|将母模底座的所有分区合并为一体|每个模盒分区保留一个母模底座|每个模盒分区保留一个母模底座，带有独立的侧面锁扣且无锁扣间隙|创建一体式母模底座，或为每个模盒分区创建独立底座|选择多分模具的底座布局|选择母模底座|选择一体式母模底座或按分模区独立的底座|选择多分模具开口|选择开放底座或完全封闭的多分模具|底足|无底足|生成不带底足的漏斗|选择底足|选择是否随漏斗一起生成底足|仅保留分模平面和所选环周围的带状结构以节省材料。|直接从模型几何体开始生成托盘外壳|轮廓|从球体开始生成托盘外壳，以获得更安全的外部轮廓|使用立方体外形|使用圆柱体外形|使外形适应模型|批量测试完成：{path} 中有 {count} 个测试用例|运行所有生成器（默认值）|运行所有多分模具选项（每个模型6种）|运行所有泥浆浇注选项（每个模型24种）"
    ),
    "AR": (
        "قاعدة مفتوحة|مغلق بالكامل|قطعة واحدة|لكل قسم|إبقاء النموذج الأصلي على القاعدة دون تمديد الغلاف إلى الأسفل|تمديد الأغلفة والقاعدة إلى الأسفل بمقدار سماكة القالب، مع إبقاء النموذج الأصلي فوق القاعدة|دمج جميع أقسام قاعدة النموذج الأصلي في قطعة واحدة|الإبقاء على قاعدة للنموذج الأصلي لكل قسم من صندوق القالب|الإبقاء على قاعدة للنموذج الأصلي لكل قسم من الصندوق، بأقفال جانبية مستقلة ودون خلوص للقفل|إنشاء قاعدة واحدة للنموذج الأصلي أو قاعدة مستقلة لكل قسم من صندوق القالب|اختيار ترتيب قاعدة القالب متعدد الأجزاء|اختيار قاعدة النموذج الأصلي|اختيار قطعة واحدة أو قاعدة مستقلة للنموذج الأصلي لكل قسم|اختيار فتحة القالب متعدد الأجزاء|اختيار قالب متعدد الأجزاء بقاعدة مفتوحة أو مغلق بالكامل|قدم|بدون قدم|إنشاء القمع دون قدم|اختيار قدم|اختيار ما إذا كان سيتم إنشاء قدم مع الأقماع|الإبقاء فقط على الأشرطة حول مستويات الفصل والحلقة المحددة لتوفير المواد.|بدء غلاف الصينية مباشرة من هندسة النموذج|محيط|بدء غلاف الصينية من كرة للحصول على محيط خارجي أكثر أمانًا|استخدام شكل خارجي مكعب|استخدام شكل خارجي أسطواني|تكييف الشكل الخارجي مع النموذج|اكتملت الاختبارات الدفعية: {count} حالة اختبار في {path}|تشغيل جميع المولدات (الإعدادات الافتراضية)|تشغيل جميع خيارات القوالب متعددة الأجزاء (6 لكل نموذج)|تشغيل جميع خيارات الصب بالطينة السائلة (24 لكل نموذج)"
    ),
}

TRANSLATIONS = {
    language: dict(zip(KEYS, row.split("|"), strict=True))
    for language, row in _ROWS.items()
}

_CHANNEL_SHAPE_KEYS = (
    "V-shaped", "Cubic", "Taper the channel ends", "Keep the channel ends square",
    "Use tapered V-shaped channel ends or square cubic ends",
)
_CHANNEL_SHAPE_ROWS = {
    "ES": "En V|Cúbico|Estrechar los extremos de los canales|Mantener cuadrados los extremos de los canales|Usar extremos de canal estrechados en V o extremos cúbicos cuadrados",
    "PT": "Em V|Cúbico|Estreitar as extremidades dos canais|Manter quadradas as extremidades dos canais|Usar extremidades de canal afuniladas em V ou extremidades cúbicas quadradas",
    "PT_BR": "Em V|Cúbico|Estreitar as extremidades dos canais|Manter quadradas as extremidades dos canais|Usar extremidades de canal afuniladas em V ou extremidades cúbicas quadradas",
    "DE": "V-förmig|Würfelförmig|Die Kanalenden verjüngen|Die Kanalenden quadratisch belassen|V-förmig verjüngte oder quadratische würfelförmige Kanalenden verwenden",
    "FR": "En V|Cubique|Effiler les extrémités des canaux|Garder les extrémités des canaux carrées|Utiliser des extrémités de canal effilées en V ou des extrémités cubiques carrées",
    "TR": "V biçimli|Kübik|Kanal uçlarını daralt|Kanal uçlarını kare tut|V biçiminde daralan kanal uçları veya kare kübik uçlar kullan",
    "IT": "A V|Cubico|Rastremare le estremità dei canali|Mantenere quadrate le estremità dei canali|Usare estremità dei canali rastremate a V o estremità cubiche quadrate",
    "RU": "V-образные|Кубические|Сузить концы каналов|Оставить концы каналов квадратными|Использовать суженные V-образные или квадратные кубические концы каналов",
    "JA": "V字形|立方体形|流路の端を先細りにする|流路の端を四角く保つ|先細りのV字形または四角い立方体形の流路端を使用",
    "KO": "V자형|정육면체형|채널 끝을 가늘게 만들기|채널 끝을 사각형으로 유지|가늘어지는 V자형 채널 끝 또는 사각형의 정육면체형 끝 사용",
    "AR": "على شكل V|مكعّب|تضييق نهايات القنوات|إبقاء نهايات القنوات مربعة|استخدام نهايات قنوات متضيقة على شكل V أو نهايات مكعبة مربعة",
    "ZH": "V形|立方体形|使流道末端逐渐变窄|保持流道末端为方形|使用逐渐变窄的V形流道末端或方形立方体末端",
}
for language, row in _CHANNEL_SHAPE_ROWS.items():
    TRANSLATIONS[language].update(zip(_CHANNEL_SHAPE_KEYS, row.split("|"), strict=True))
