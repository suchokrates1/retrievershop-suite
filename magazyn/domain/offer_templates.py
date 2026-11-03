"""Jeden wzór opisu na serię.

Zmienne: kolor, rozmiar, dla jakich psów. Liczby i rasy pochodzą z opisów
Allegro już zapisanych w magazynie. Gdy aukcje tej samej serii podają
różne widełki, wzór bierze tabelę, która wymienia wszystkie rozmiary,
a nie pojedynczy nagłówek jednej aukcji.

Układ aukcji:
1. zdjęcie po lewej, tekst po prawej
2. tekst po lewej, zdjęcie po prawej
3. rozmiar i zdjęcie tabeli, jeśli jest w galerii
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape


@dataclass(frozen=True)
class SizeFit:
    weight: str
    dogs: str = ""
    extra: str = ""


@dataclass(frozen=True)
class SeriesTemplate:
    category: str
    series: str
    lead: str
    features: tuple[str, ...]
    paragraphs: tuple[str, ...] = ()
    measure: str = ""
    sizes: dict[str, SizeFit] = field(default_factory=dict)
    publish: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return (self.category, self.series)


def _premium_sizes() -> dict[str, SizeFit]:
    # Tabela z aktywnego opisu Front Line Premium, który wymienia XS–XL.
    # Część aukcji L podaje osobno „18–28 kg”. Tego wariantu nie mieszam z tabelą.
    return {
        "XS": SizeFit("do 4 kg", "Yorkshire Terrier, Pinczer Miniaturowy, Papillon, Chihuahua, Grzywacz Chiński", "szyja 22–37 cm, klatka 33–42 cm"),
        "S": SizeFit("do 9 kg", "Pudel Miniaturowy, Mops, Shih Tzu, Jack Russell Terrier, Jamnik, Cavalier King Charles Spaniel", "szyja 30–47 cm, klatka 40–56 cm"),
        "M": SizeFit("do 16 kg", "Whippet, Beagle, Basenji, Buldog Francuski", "szyja 32–50 cm, klatka 52–65 cm"),
        "L": SizeFit("do 27 kg", "Husky, Border Collie, Shar Pei, Bulterier, Toller", "szyja 38–56 cm, klatka 64–80 cm"),
        "XL": SizeFit("do 38 kg", "Owczarek Niemiecki, Labrador, Golden Retriever, Bokser, Doberman", "szyja 52–65 cm, klatka 78–96 cm"),
    }


_TEMPLATES: tuple[SeriesTemplate, ...] = (
    SeriesTemplate(
        category="Szelki",
        series="Front Line Premium",
        lead="Szelki guard z odpinanym przodem i zapięciem easy walk.",
        paragraphs=(
            "Regulacja w czterech punktach dopasowuje szelki także do nietypowej budowy. Przy dokładnym dopasowaniu trzymają psy, które wyślizgują się z szelek. To dobre pierwsze szelki około 8–9 miesiąca i zostają z psem, gdy przybierze masy. Mogą zastąpić obrożę.",
            "Smycz zapięta z przodu obraca ciągnącego psa w stronę człowieka, więc nie może napierać do przodu. Da się oduczyć ciągnięcia także u starszego psa. Przód jest odpinany i jest dodatkowe zapięcie wokół szyi, więc szelek nie przekłada się przez głowę.",
            "Smycz wpina się w elementy ze stopu cynku. Zapięcie przy szyi jest aluminiowe. Wierzch to bawełna Oxford: piasek się strzepuje, zabrudzenie przeciera gąbką, po błocie można wyprać w pralce. Spód to siateczka MESH.",
        ),
        features=(
            "Dwa punkty smyczy: grzbiet, przesunięty dalej niż we wcześniejszym Front Line, i przód easy walk.",
            "Kieszeń na lampkę LED, także Lumen Led.",
            "Klamry Duraflex.",
            "Nylonowa rączka: schody, wchodzenie do auta, pas samochodowy, przytrzymanie psa.",
            "Odblaskowe przeszycie 3M Scotchlite.",
            "Kieszonka na identyfikator.",
            "Regulacja w czterech punktach.",
        ),
        measure=(
            "Na granicy rozmiarów wybierz większy. Pies około 8–10 miesięcy, który rośnie i jest na granicy, też bierze większy. "
            "Jeśli w większości modeli nosi L, przy tych szelkach najprawdopodobniej potrzebny jest XL."
        ),
        sizes=_premium_sizes(),
    ),
    SeriesTemplate(
        category="Szelki",
        series="Front Line",
        lead="Szelki guard z regulacją w czterech punktach i zapięciem easy walk.",
        paragraphs=(
            "Dopasowanie w czterech punktach zostawia zapas, gdy pies jeszcze rośnie. Zapięcie z przodu służy do nauki luźnej smyczy i trzeba je dokładnie dopasować. Sprawdzają się przy dogtrekkingu, bieganiu, rolkach i rowerze.",
            "Uchwyt z tyłu nadaje się do pasa samochodowego, schodów i wchodzenia do auta. Materiał można wyprać w pralce.",
        ),
        features=(
            "Wierzch odporny na zarysowania, spód z oddychającej siateczki.",
            "Dwa punkty smyczy, na grzbiecie i na klatce. Klamry ze stopu cynku.",
            "Nylonowa rączka.",
            "Odblaskowe przeszycie 3M Scotchlite.",
            "Kieszonka na identyfikator.",
            "Regulacja w czterech punktach.",
        ),
        measure="Obwód zmierz w miejscu z rysunku przy tabeli. Centymetry i wagi są z tabeli Front Line, tej samej co przy Premium.",
        sizes=_premium_sizes(),
    ),
    SeriesTemplate(
        category="Szelki",
        series="Front Line Cordura",
        lead="Szelki guard z Cordury. Na TipTopie ta karta nazywa się Front Line Premium Cordura.",
        paragraphs=(
            "Przód jest odpinany, a przy szyi jest aluminiowa klamra, więc szelek nie przekłada się przez głowę. Regulacja w czterech punktach dopasowuje też nietypową budowę i zmniejsza ryzyko wysunięcia się.",
            "Dwa punkty smyczy: tylny aluminiowy do codziennych spacerów i przedni easy walk. Rączkę można przełożyć przez pas bezpieczeństwa.",
            "Wierzch to Cordura 160D i 305D, środek to siateczka Sandwich Mesh. Taśmy nylonowe mają elementy odblaskowe 3M. Jest miejsce na lampkę LED.",
        ),
        features=(
            "Cordura odporna na ścieranie, rozdarcia i wilgoć.",
            "Odpinany przód i aluminiowa klamra przy szyi.",
            "Cztery punkty regulacji.",
            "Dwa punkty smyczy, w tym easy walk.",
            "Rączka do przytrzymania i do pasa w samochodzie.",
            "Miejsce na lampkę LED.",
        ),
        sizes=_premium_sizes(),
    ),
    SeriesTemplate(
        category="Szelki",
        series="Front Line Premium Cordura",
        lead="Front Line Premium uszyty z Cordury 160D i 305D.",
        paragraphs=(
            "Przód jest odpinany, a przy szyi jest aluminiowa klamra, więc szelek nie przekłada się przez głowę. Regulacja w czterech punktach dopasowuje też nietypową budowę i zmniejsza ryzyko wysunięcia się. Krój nie ogranicza łopatek.",
            "Dwa punkty smyczy: tylny aluminiowy do spacerów i przedni easy walk do treningu luźnej smyczy. Rączkę można przełożyć przez pas bezpieczeństwa.",
            "Wnętrze to siateczka Sandwich Mesh. Taśmy nylonowe mają odblask 3M. Jest miejsce na lampkę LED.",
        ),
        features=(
            "Cordura 160D i 305D, odporna na ścieranie, rozdarcia i wilgoć.",
            "Odpinany przód.",
            "Cztery punkty regulacji.",
            "Easy walk z przodu i aluminiowe kółko z tyłu.",
            "Rączka.",
            "Miejsce na lampkę LED.",
        ),
        sizes=_premium_sizes(),
    ),
    SeriesTemplate(
        category="Szelki",
        series="Tropical",
        lead="Szelki na bazie wykroju Front Line, z odpinaną szyją i kieszenią na lampkę.",
        paragraphs=(
            "Aluminiowe zapięcie wokół szyi pozwala założyć szelki bez przekładania przez głowę, także lękliwemu psu. Regulacja w czterech punktach obejmuje psy około 8–9 miesięcy i zostaje, gdy pies urośnie.",
            "Easy walk z przodu obraca ciągnącego psa w stronę człowieka. Wykrój na klatce ma kształt Y. Rączka z tyłu służy do przytrzymania i do pasa samochodowego. Można je wyprać.",
        ),
        features=(
            "Wierzch z bawełny, spód z miękkiej siateczki.",
            "Regulacja w czterech punktach.",
            "Dwa zapięcia smyczy: grzbiet i przód.",
            "Kieszeń na lampkę LED oraz na identyfikator lub lokalizator.",
            "Odblask 3M Scotchlite.",
            "Rączka z tyłu.",
        ),
        measure="Obwód zmierz w miejscu z rysunku.",
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Adventure Soft",
        lead="Ultralekkie szelki z wodoodpornej Cordury.",
        paragraphs=(
            "Cordura jest oddychająca i wodoodporna. Paski są z elastycznej taśmy. Klamry to Duraflex. Przód jest odpinany, więc szelek nie wkłada się przez głowę. Easy walk z przodu wspiera naukę luźnej smyczy.",
            "Maksymalna waga psa dla tego modelu to 40/42 kg. Szelki można prać. Nadają się do trekkingu, dogtrekkingu, auta i codziennego noszenia.",
        ),
        features=(
            "Cordura wodoodporna i oddychająca.",
            "Elastyczne taśmy i klamry Duraflex.",
            "Aluminiowe zapięcie przy szyi.",
            "Easy walk i regulacja w czterech punktach.",
            "Maksymalna waga z karty: 40/42 kg.",
        ),
        measure="Rozmiar dobierz po obwodzie z rysunku.",
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Lumen",
        lead="Szelki guard z odblaskiem na całej powierzchni i kieszenią na lampkę Lumen Led.",
        paragraphs=(
            "Regulacja w czterech punktach. Środek to miękka, oddychająca siateczka. Odblask pokrywa całe szelki, a kieszeń jest na wodoodporną lampkę Lumen Led.",
            "Dwa punkty smyczy, z aluminium, są na grzbiecie i na klatce. Nylonowa rączka służy też do pasa w samochodzie.",
        ),
        features=(
            "Odblask na całych szelkach.",
            "Kieszeń na lampkę Lumen Led.",
            "Dwa punkty smyczy ze stopu aluminium.",
            "Regulacja w czterech punktach.",
            "Nylonowa rączka.",
        ),
        measure="Szyję zmierz poniżej obroży, klatkę około 5–10 cm za łapkami, w miejscu z rysunku.",
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Safe Hiking",
        lead="Szelki antyucieczkowe dla psów, które wychodzą z uprzęży.",
        paragraphs=(
            "Na zewnątrz jest tkanina Oxford, w środku neopren. Dwa miejsca na smycz: z tyłu i z przodu, easy walk. Aluminiowe zapięcie przy szyi pozwala zdjąć szelki bez przekładania przez głowę.",
            "Regulacja jest w sześciu punktach: przy szyi, za łapami i za mostkiem. Opis wymienia też trzy pasy regulujące. Na górze jest panel na rzepy z literami i cyframi. Prać do 30 stopni.",
        ),
        features=(
            "Oxford na zewnątrz, neopren w środku.",
            "Regulacja przy szyi, za łapami i za mostkiem.",
            "Dwa punkty smyczy, w tym easy walk.",
            "Rączka.",
            "Odblask na taśmach i odblaskowe logo.",
            "Panel na rzepy. Personalizowanych rzepów nie ma w zestawie.",
            "Pranie do 30 stopni.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Security",
        lead="Szelki guard do dogtrekkingu, skijoringu i tropienia.",
        paragraphs=(
            "Zapięcie smyczy leży dalej na grzbiecie niż w innych modelach, pod psa idącego z przodu. Są dwa punkty, na grzbiecie i na klatce, oba ze stopu cynku. Rączka pomaga przy schodach, aucie i starszym psie.",
            "Nie mają regulacji z przodu i nie każdy pies da się w nich idealnie dopasować. Wierzch jest odporny na zarysowania, na grzbiecie jest fragment ze skóry ekologicznej. Odblask to 3M Scotchlite.",
        ),
        features=(
            "Odpinane przy szyi, bez przekładania przez głowę.",
            "Dwa punkty smyczy ze stopu cynku.",
            "Rączka na grzbiecie.",
            "Odblask 3M Scotchlite.",
            "Brak regulacji z przodu.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Tracker",
        lead="Szelki guard z lampką LED w zestawie i uchwytem na lokalizator.",
        paragraphs=(
            "Zewnątrz to tkanina UHMWPE, środek Cordura, podszewka Oxford 500D. Aluminiowa klamra przy szyi pozwala założyć szelki bez przekładania przez głowę. Regulacja w czterech punktach, z przodu jest easy walk.",
            "W zestawie jest wodoodporna lampka IP65, akumulatorowa, z 19 trybami. W lampce jest uchwyt na AirTag albo Huawei Tag. Lokalizatora nie ma w zestawie.",
        ),
        features=(
            "Lampka LED IP65, 19 trybów, w zestawie.",
            "Uchwyt na AirTag lub Huawei Tag. Lokalizator osobno.",
            "UHMWPE, Cordura i Oxford 500D.",
            "Easy walk i cztery punkty regulacji.",
            "Aluminiowe zapięcie przy szyi.",
            "Rączka.",
        ),
        measure="Na granicy rozmiarów wybierz większy. Szyję zmierz poniżej obroży, klatkę w najszerszym miejscu za przednimi łapami.",
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Blossom",
        lead="Szelki guard o wykroju Y, z Cordury, we wzorze kwiatowym.",
        paragraphs=(
            "Wierzch to Cordura, spód siateczka. Jest easy walk, aluminiowe zapięcie przy szyi i kieszeń na lampkę LED oraz mniejsza kieszeń przy przednim zapięciu na lokalizator. Rączka służy do pasa samochodowego.",
            "Smycz z przodu obraca ciągnącego psa w stronę człowieka. Regulacja jest przy szyi i przy klatce. Można prać. Dla szczeniaka, który ma już około 8–9 miesięcy. Odblask to 3M Scotchlite.",
        ),
        features=(
            "Cordura i siateczka.",
            "Regulacja przy szyi i przy klatce.",
            "Easy walk i aluminiowe zapięcie przy szyi.",
            "Kieszeń na lampkę LED i kieszeń na lokalizator.",
            "Rączka do pasa samochodowego.",
            "Odblask 3M Scotchlite.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Active",
        lead="Lekkie szelki z siateczki, na sport i na spacer.",
        paragraphs=(
            "Materiał jest lekki i szybko schnie, także po kąpieli. Od środka są wyścielone, żeby nie zjeżdżały w ruchu. Polecane jako szelki flyballowe.",
            "Odblask to 3M Scotchlite. Klamry są ze stopu cynku.",
        ),
        features=(
            "Siateczka, szybkoschnące.",
            "Odblask 3M Scotchlite.",
            "Klamry ze stopu cynku.",
            "Wyścielenie od wewnątrz.",
        ),
        measure="Tabela podaje obwód klatki.",
        sizes={
            "XXS": SizeFit("", "", "klatka 42–50 cm"),
            "XS": SizeFit("", "", "klatka 48–56 cm"),
            "S": SizeFit("", "", "klatka 54–64 cm"),
            "M": SizeFit("", "", "klatka 62–72 cm"),
            "L": SizeFit("", "", "klatka 70–82 cm"),
            "XL": SizeFit("", "", "klatka 80–92 cm"),
        },
    ),
    SeriesTemplate(
        category="Szelki",
        series="Adventure Dog",
        lead="Lekkie szelki z wodoodpornym wierzchem i podszewką z mikrowłókien.",
        paragraphs=(
            "Spód to mikrowłókna z zamszu. Klamry Duraflex, z przodu dodatkowe zapięcie do nauki luźnej smyczy. Wykrój klatki ma kształt Y. Aluminiowe okucia przy szyi pozwalają założyć szelki bez przekładania przez głowę.",
            "Taśmy są odblaskowe, 3M Scotchlite. Regulacja jest przy szyi i przy klatce. Nadają się do agility, dogfrisbee i flyballa oraz dla psów, u których nie zaleca się obroży.",
        ),
        features=(
            "Wodoodporny wierzch, podszewka z mikrowłókien.",
            "Klamry Duraflex.",
            "Easy walk i wykrój Y.",
            "Aluminiowe zapięcie przy szyi.",
            "Odblask 3M Scotchlite.",
            "Regulacja przy szyi i przy klatce.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Obroża",
        series="Active",
        lead="Obroża z nylonu i siateczki, na sport i na spacer.",
        paragraphs=(
            "Nylonowa taśma jest obszyta miękką siateczką, więc całkowita szerokość jest trochę większa niż sama taśma w tabeli. Przeszycie to 3M Scotchlite. Nadaje się do pływania, flyballu i dogfrisbee. Jest szybkoschnąca.",
        ),
        features=(
            "Nylon i miękka siateczka.",
            "Odblask 3M Scotchlite.",
            "Szybkoschnąca.",
            "Szerokość w tabeli dotyczy samej taśmy.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Obroża",
        series="Tropical",
        lead="Obroża do kompletu z szelkami i smyczą Tropical.",
        paragraphs=(
            "Miękkie przeszycie z siateczki i klamra Duraflex. Siateczka dodaje około 0,5 cm do szerokości samej kolorowej taśmy. Jest szybkoschnąca.",
        ),
        features=(
            "Miękka siateczka, około 0,5 cm ponad szerokość taśmy.",
            "Klamra Duraflex.",
            "Regulacja.",
            "Szybkoschnąca.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Obroża",
        series="Lumen",
        lead="Obroża z odblaskiem na całej taśmie i kieszenią na lampkę.",
        paragraphs=(
            "Kieszeń jest pod lampkę Lumen LED. Klamra jest ze stopu cynku i ma wytrzymać szarpnięcie. Lekka, do spacerów po zmroku i do sportu.",
        ),
        features=(
            "Odblask na całej obroży.",
            "Kieszeń na lampkę Lumen LED.",
            "Klamra ze stopu cynku.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Kamizelka",
        series="Chłodząca",
        lead="Kamizelka chłodząca, moczona w wodzie.",
        paragraphs=(
            "Trzy warstwy: zewnętrzna odprowadza wilgoć, środkowa trzyma wodę, wewnętrzna chłodzi. Kamizelkę moczy się w zimnej wodzie, wykręca i zakłada. Gdy woda wyparuje, moczy się ją ponownie.",
            "Zapięcia ze stopu cynku pozwalają podpiąć smycz, więc może działać jak szelki. Jest podwójny zamek, ściągacz na dole, rzepy i odblask. Opis podaje też, że zimą działa jak ogrzewająca derka.",
        ),
        features=(
            "Chłodzenie wyparne po namoczeniu.",
            "Zapięcia ze stopu cynku do smyczy.",
            "Podwójny zamek, ściągacz i rzepy.",
            "Odblask.",
            "Po namoczeniu chłodzi. Opis podaje też użycie zimą jako derki.",
        ),
        measure="Rozmiar dobierz po obwodzie szyi i klatki, według zakresu przy rysunku.",
        sizes={},
    ),
    SeriesTemplate(
        category="Kapok",
        series="Dive",
        lead="Kapok do wody i do rehabilitacji.",
        paragraphs=(
            "Dopasowuje się do sylwetki i nie krępuje ruchów. Jest rączka do wyciągnięcia psa z wody albo przytrzymania. Do metalowego kółka przy rączce można przypiąć smycz, gdy pies nie ma obroży. Ma odblaski.",
        ),
        features=(
            "Regulacja dopasowująca do sylwetki.",
            "Rączka do wyciągania z wody.",
            "Metalowe kółko na smycz.",
            "Odblaski.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Pas samochodowy",
        series="Premium",
        lead="Wzmocniony pas, który wpina szelki w zapięcie samochodowe.",
        paragraphs=(
            "Karabińczyk zapina się przy szelkach. Zapięcie ma 12 cm szerokości i 7 cm wysokości. Opis poleca komplet z szelkami Front Line. Ma ograniczyć ruch psa w aucie.",
        ),
        features=("Karabińczyk do szelek.", "Wzmocniona wersja."),
        sizes={},
    ),
    SeriesTemplate(
        category="Amortyzator",
        series="Premium",
        lead="Lekki amortyzator do dowolnej smyczy, szelek albo obroży.",
        paragraphs=(
            "Chroni kręgosłup, nadgarstki i ramiona przed szarpnięciem. Na spacerze zostaje wpięty, a na trening luźnej smyczy albo easy walk łatwo go odpiąć, bo wtedy sygnał ma iść bez sprężyny.",
            "Sprawdza się na spacerze, dogtrekkingu i przy rowerze. Do psów średnich, maksymalnie 30 kg.",
        ),
        features=(
            "Szerokość 2 cm.",
            "Długość w spoczynku 48 cm, po rozciągnięciu 75 cm.",
            "Do 30 kg.",
            "Wpina się w smycz, szelki albo obrożę.",
        ),
    ),
    SeriesTemplate(
        category="Pas trekkingowy",
        series="Trek Go",
        lead="Pas biodrowy do biegania, z nerką i bidonem w komplecie.",
        paragraphs=(
            "Obwód pasa od 65 do 125 cm. Klamra ma trzymać pas w jednym miejscu. Są odblaski.",
        ),
        features=(
            "Bidon w komplecie, kieszeń przyjmuje różne pojemności.",
            "Dwie kieszenie na smakołyki i telefon.",
            "Wyjście na woreczki albo słuchawki.",
            "Odblaski.",
            "Obwód 65–125 cm.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Lumen Lite",
        lead="Lżejsze szelki Lumen, z neoprenem i kieszenią na lampkę.",
        paragraphs=(
            "Regulacja w czterech punktach. Środek to miękki neopren, żeby szelki nie zjeżdżały i nie obcierały. Odblask jest na całej powierzchni, kieszeń na wodoodporną lampkę Lumen Led.",
            "Przód jest odpinany. Klamra ze stopu cynku. Nylonowa rączka służy też do pasa w samochodzie. Są szybkoschnące.",
        ),
        features=(
            "Odpinany przód.",
            "Neopren od środka.",
            "Odblask na całych szelkach.",
            "Kieszeń na lampkę Lumen Led.",
            "Klamra ze stopu cynku.",
            "Nylonowa rączka.",
        ),
        measure="Na granicy rozmiarów wybierz większy. Tabela podaje obwód klatki.",
        sizes={
            "XS": SizeFit("", "", "klatka 33–43 cm"),
            "S": SizeFit("", "", "klatka 43–56 cm"),
            "M": SizeFit("", "", "klatka 56–69 cm"),
            "L": SizeFit("", "", "klatka 69–81 cm"),
            "XL": SizeFit("", "", "klatka 81–107 cm"),
        },
    ),
    SeriesTemplate(
        category="Smycz",
        series="Active",
        lead="Smycz z nylonu obszytego siateczką i odblaskiem 3M Scotchlite.",
        paragraphs=(
            "Rozmiar S, długość 200 cm. Karabińczyk jest dobrany do tego rozmiaru. W rączce jest miejsce na dane właściciela.",
            "Nylon jest obszyty siateczką. Odblask 3M Scotchlite idzie też po uchwycie.",
        ),
        features=(
            "Nylon obszyty siateczką, około 0,5 cm ponad szerokość taśmy.",
            "Odblask 3M Scotchlite, także w uchwycie.",
            "Miejsce na dane właściciela.",
        ),
        sizes={
            "S": SizeFit("do 18 kg", "Cavalier, Mops, Shih Tzu, Maltańczyk, Pekińczyk, Buldog francuski"),
            "M": SizeFit("do 35 kg", "Border Collie, Golden Retriever, Toller, Beagle, Wyżeł"),
            "L": SizeFit("do 70 kg", "Berneńczyk, Nowofundland, Bernardyn, Rottweiler"),
        },
    ),
    SeriesTemplate(
        category="Smycz",
        series="Active Pro+",
        lead="Smycz przepinana, 250 cm, z siateczką i odblaskiem 3M Scotchlite.",
        paragraphs=(
            "Dodatkowe zapięcia skracają smycz albo pozwalają prowadzić dwa psy. Rączka jest miękka. W środku jest miejsce na dane właściciela. Szerokość taśmy na karcie dużego rozmiaru to 2,5 cm plus około 0,5 cm siateczki.",
        ),
        features=(
            "Długość 250 cm.",
            "Przepinana, da się skrócić i prowadzić dwa psy.",
            "Odblask 3M Scotchlite.",
            "Miękka rączka i miejsce na dane właściciela.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Smycz",
        series="Lumen",
        lead="Smycz z odblaskiem i kieszenią na lampkę.",
        paragraphs=(
            "Lekka, z miękką rączką i kieszonką na latarkę. Łatwa w czyszczeniu. Karabińczyk zależy od rozmiaru.",
        ),
        features=(
            "Odblask.",
            "Kieszonka na latarkę.",
            "Miękka rączka.",
        ),
        sizes={
            "S": SizeFit("do 18 kg", "Cavalier, Mops, Shih Tzu, Maltańczyk, Pekińczyk, Buldog francuski"),
            "M": SizeFit("do 35 kg", "Border Collie, Golden Retriever, Toller, Beagle, Wyżeł"),
        },
    ),
    SeriesTemplate(
        category="Obroża",
        series="Dogi",
        lead="Obroża z miękkiego nylonu, do kompletu ze smyczą Dogi.",
        paragraphs=(
            "Jest aluminiowy zaczep i osobne zapięcie na adresówkę. Nylon jest oddychający i szybkoschnący.",
        ),
        features=(
            "Miękki, oddychający nylon.",
            "Aluminiowy zaczep.",
            "Zapięcie na adresówkę.",
            "Szybkoschnąca.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Szelki",
        series="Outdoor",
        lead="Szelki dla psa pracującego, z rzepami do personalizacji.",
        paragraphs=(
            "Po obu stronach są duże rzepy. Logo da się zdjąć. Dodatkowy pas piersiowy rozkłada ciężar. Wyściółka to miękka siateczka i elastyczna gąbka.",
            "Jest mocna rączka. Odblask to 3M Scotchlite. Klamry są ze stopu cynku.",
        ),
        features=(
            "Rzepy po obu stronach i zdejmowane logo.",
            "Dodatkowy pas piersiowy.",
            "Siateczka i gąbka od środka.",
            "Rączka.",
            "Odblask 3M Scotchlite.",
            "Klamry ze stopu cynku.",
        ),
        measure="Tabela podaje obwód klatki. Rozmiar 2XL odpowiada wierszowi XXL.",
        sizes={
            "XS": SizeFit("", "", "klatka 40–53 cm"),
            "S": SizeFit("", "", "klatka 49–67 cm"),
            "M": SizeFit("", "", "klatka 58–76 cm"),
            "L": SizeFit("", "", "klatka 63–85 cm"),
            "XL": SizeFit("", "", "klatka 71–96 cm"),
            "2XL": SizeFit("", "", "klatka 82–115 cm"),
        },
    ),
    SeriesTemplate(
        category="Smycz",
        series="Handy",
        lead="Automatyczna smycz, rozmiar M, taśma do 5 metrów.",
        paragraphs=(
            "Rozmiar M: taśma do 5 metrów, psy do 25 kg. Przy wylocie taśmy jest element, który ją prostuje, żeby się nie skręcała i nie zacinała. Hamulec obsługuje się jedną ręką.",
            "Taśma jest odblaskowa, karabińczyk ze stopu cynku. Jest pasek na ramię.",
        ),
        features=(
            "Długość do 5 m.",
            "Pasek na ramię.",
            "Odblaskowa taśma.",
            "Hamulec jedną ręką.",
            "Karabińczyk ze stopu cynku.",
            "Do 25 kg.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Smycz",
        series="Adventure",
        lead="Smycz z amortyzatorem, na spacer i na trening.",
        paragraphs=(
            "Amortyzator odciąża kręgosłup, nadgarstki i ramiona. Główna rączka jest podszyta neoprenem. Przy karabińczyku jest drugi uchwyt, żeby przytrzymać psa krótko.",
            "Długość 120 cm, po naciągnięciu do 160 cm. Kompletuje się z szelkami Adventure i Adventure Soft.",
        ),
        features=(
            "Długość 120–160 cm.",
            "Neopren na rączce.",
            "Drugi uchwyt przy karabińczyku.",
            "Rozmiary różnią się karabińczykiem.",
        ),
        sizes={
            "S": SizeFit("do 18 kg", "Cavalier, Mops, Shih Tzu, Maltańczyk, Pekińczyk, Buldog francuski"),
            "M": SizeFit("do 35 kg", "Border Collie, Golden Retriever, Toller, Beagle, Wyżeł"),
            "L": SizeFit("powyżej 35 kg", "Berneńczyk, Nowofundland, Bernardyn, Rottweiler"),
        },
    ),
    SeriesTemplate(
        category="Saszetki",
        series="Standard",
        lead="Saszetka na przysmaki, do paska albo plecaka.",
        paragraphs=(
            "Mieści przysmaki i dodatkową porcję karmy. Jest kieszeń z siateczki na woreczki. Da się ją wyczyścić.",
            "Dwa zaczepy: materiałowa szlufka na pasek i metalowy zacisk na kieszeń, plecak albo pasek.",
        ),
        features=(
            "Szlufka i metalowy zacisk.",
            "Kieszeń z siateczki na woreczki.",
        ),
        sizes={
            "S": SizeFit("", "", "12,5 × 7 × 13 cm"),
            "M": SizeFit("", "", "16 × 7 × 20 cm"),
        },
    ),
    SeriesTemplate(
        category="Saszetki",
        series="Trail Bag",
        lead="Ultralekka nerka na spacer i trening.",
        paragraphs=(
            "Na ramieniu jest kieszeń na woreczki, z przodu kieszeń na zamek na telefon, z boku elastyczna kieszeń na butelkę. W środku jest przegroda na portfel, klucze i drobiazgi.",
        ),
        features=(
            "Wymiary 30 × 17 cm.",
            "Kieszeń na woreczki.",
            "Kieszeń na telefon.",
            "Kieszeń na butelkę.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Saszetki",
        series="Treat Basic",
        lead="Torebka na ramię na przysmaki i drobiazgi.",
        paragraphs=(
            "Trzy kieszenie: otwarta z zewnątrz i dwie wewnętrzne na wodoodporny zamek. Jest uchwyt na klucze i kieszeń na woreczki. Materiał jest z recyklingu. Pasek reguluje się od 64 do 122 cm.",
        ),
        features=(
            "Wymiary 16 × 9 × 20 cm.",
            "Pasek 64–122 cm.",
            "Uchwyt na klucze.",
            "Kieszeń na woreczki.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Saszetki",
        series="V1",
        lead="Sakwa z rzepami, do szelek, plecaka albo paska.",
        paragraphs=(
            "Oxford 600D, wodoodporna. W środku są przegródki na klucze, telefon, mapę i smakołyki. Na dole jest otwór na woreczki. Z przodu panel na rzep, litery i cyfry. Pasuje do szelek Hiking. Można prać w 30 stopniach.",
        ),
        features=(
            "Wymiary 10,5 × 16,5 × 4 cm.",
            "Oxford 600D.",
            "Otwór na woreczki.",
            "Panel na rzep.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Saszetki",
        series="V2",
        lead="Większa sakwa z rzepami, do szelek, plecaka albo paska.",
        paragraphs=(
            "Oxford 600D, wodoodporna. W środku są przegródki na klucze, telefon, mapę i smakołyki. Na dole jest otwór na woreczki. Z przodu panel na rzep, litery i cyfry. Pasuje do szelek Hiking. Można prać w 30 stopniach.",
        ),
        features=(
            "Wymiary 16 × 11,5 × 4 cm.",
            "Oxford 600D.",
            "Otwór na woreczki.",
            "Panel na rzep.",
        ),
        sizes={},
    ),
    SeriesTemplate(
        category="Linka",
        series="",
        lead="Wodoodporna linka treningowa Hexa, 5 m.",
        paragraphs=(
            "Taśma o strukturze plastra miodu jest pokryta termoplastycznym poliuretanem. Nie chłonie wody ani błota, wystarczy ją opłukać. Nie rozciąga się i nie jest odporna na przegryzienie.",
            "Karabińczyk i okucia są czarne. Szerokość taśmy 13 mm, długość 5 m.",
        ),
        features=(
            "Materiał Hexa, powłoka TPU.",
            "Długość 5 m, szerokość 13 mm.",
            "Czarny karabińczyk sprężynowy.",
            "Nieodporna na przegryzienie.",
        ),
        sizes={},
    ),
)


_BY_KEY = {item.key: item for item in _TEMPLATES}


def template_for(category: str | None, series: str | None) -> SeriesTemplate | None:
    return _BY_KEY.get(((category or "").strip(), (series or "").strip()))


def _fit_line(size: str, fit: SizeFit) -> str:
    parts = [size]
    if fit.weight:
        parts.append(fit.weight)
    if fit.dogs:
        parts.append(fit.dogs)
    if fit.extra:
        parts.append(fit.extra)
    return " — ".join(parts)


def _photo_or_empty(photos: list[str], index: int) -> str:
    if index < len(photos):
        return photos[index]
    return ""


def pick_size_chart_url(photos: list[str]) -> str:
    markers = ("rozmiar", "tabela", "size-chart", "size_chart", "wymiar")
    for url in photos:
        lowered = url.lower()
        if any(marker in lowered for marker in markers):
            return url
    return ""


def render_offer_html(
    template: SeriesTemplate,
    *,
    color: str,
    photos: list[str],
    only_size: str | None = None,
) -> str:
    """Złóż opis. only_size zostawia w tabeli jeden rozmiar, pod wysyłkę tej aukcji."""
    color_text = escape((color or "").strip() or "do wyboru")
    left_photo = escape(_photo_or_empty(photos, 0))
    right_photo = escape(_photo_or_empty(photos, 1))
    chart = escape(pick_size_chart_url(photos))
    features = "".join(f"<li>{escape(item)}</li>" for item in template.features)
    body_source = template.paragraphs or ((template.lead,) if template.lead else ())
    body = "".join(f"<p>{escape(item)}</p>" for item in body_source)
    size_rows = _size_rows(template, only_size)
    measure = f"<p>{escape(template.measure)}</p>" if template.measure else ""
    left_img = f'<img src="{left_photo}" alt="">' if left_photo else ""
    right_img = f'<img src="{right_photo}" alt="">' if right_photo else ""
    chart_img = f'<img src="{chart}" alt="Tabela rozmiarów">' if chart else ""
    feature_block = f"<ul>{features}</ul>" if template.features else ""
    size_block = f"<ul>{size_rows}</ul>" if size_rows else ""
    return (
        '<div class="auction">'
        '<div class="auction-row">'
        f"{left_img}"
        "<div class=\"auction-text\">"
        f"<h1>{escape(template.series)}</h1>"
        f"<h2>{color_text}</h2>"
        f"<p><b>Kolor:</b> {color_text}</p>"
        f"{body}"
        "</div></div>"
        '<div class="auction-row auction-row-reverse">'
        f"<div class=\"auction-text\">{feature_block}</div>"
        f"{right_img}"
        "</div>"
        '<div class="auction-size">'
        "<h2>Rozmiar</h2>"
        f"{size_block}{measure}{chart_img}"
        "</div></div>"
    )


def _size_rows(template: SeriesTemplate, only_size: str | None) -> str:
    items = template.sizes
    if only_size:
        key = only_size.strip()
        fit = items.get(key)
        if fit is None:
            return f"<li>{escape(key)}</li>"
        return f"<li>{escape(_fit_line(key, fit))}</li>"
    if not items:
        return ""
    chosen = only_size.strip() if only_size else None
    rows = []
    for size, fit in items.items():
        line = escape(_fit_line(size, fit))
        if chosen and size == chosen:
            line = f"<b>{line}</b>"
        rows.append(f"<li>{line}</li>")
    return "".join(rows)


def offer_title(template: SeriesTemplate, *, color: str, size: str | None = None) -> str:
    parts = [template.category, "Truelove", template.series, (color or "").strip()]
    if size:
        parts.append(size.strip())
    return " ".join(part for part in parts if part)
