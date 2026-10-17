# Arquitetura

Como o Traço Firme funciona por dentro: módulos, caminho de um traço, algoritmos e as
decisões tomadas.

## Stack

- **Python 3.10+ com PySide6 (Qt 6)**. O Qt é o mesmo framework do Krita e entrega a caneta
  pelo Windows Ink (`QTabletEvent`), com pressão e coordenadas subpixel. Um app web ou
  Electron só teria Windows Ink, nunca WinTab.
- **numpy**: ajuste de curvas, alisamento vetorizado e ajuste de elipse.
- **WinTab via `ctypes`**: o Qt 6 removeu a opção pública de usar WinTab, então o
  `wintab32.dll` do driver é lido diretamente (ver `wintab.py`).

## Módulos (`tracofirme/`)

| Módulo | Responsabilidade | Usa Qt? |
|---|---|---|
| `__main__.py` | Inicialização: tradução pt-BR dos botões do Qt, janela, abrir `.traco` da linha de comando | sim |
| `window.py` | Janela principal: barra de ferramentas, painel de ajustes, menus, arquivos, exportação | sim |
| `widgets.py` | Controles do painel: `SliderRow`, `Toggle`, `Section`, `ColorSwatches` | sim |
| `dialogs.py` | Diálogos: tamanho da folha, mesa digitalizadora (com medidor de pressão) e guia rápido | sim |
| `icons.py` | Ícones gerados da fonte Segoe Fluent Icons / MDL2 Assets do Windows | sim |
| `canvas.py` | Área de desenho: entrada da caneta, estabilização ao vivo, formas, borracha, vista e cache | sim |
| `document.py` | Modelo: `Stroke` (traço imutável), `Document` (traços, desfazer/refazer, arquivo `.traco`) | não |
| `geometry.py` | Reamostragem, alisamento, cantos vivos, pontas finas, contorno e borracha | não |
| `curvefit.py` | Ajuste de curvas Bézier cúbicas (Schneider) | não |
| `shapes.py` | Reconhecimento de formas e "embelezamento" (alinhamento, retângulo, quadrado) | não |
| `filters.py` | Filtro 1€ (estabilização ao vivo que se adapta à velocidade) | não |
| `render.py` | Traço → `QPainterPath`; exportação PNG e SVG | sim |
| `settings.py` | Preferências (`QSettings`, no registro do Windows) | sim |
| `wintab.py` | Backend WinTab por `ctypes` | sim |
| `winink.py` | Desliga "segurar = clique direito" e os gestos do Windows Ink na janela | não |
| `diag.py` | Log de diagnóstico em JSON Lines (desligado por padrão) | não |

Os módulos sem Qt são testados diretamente com pytest.

## Representação

Um **traço** é uma lista de pontos `(x, y, r)` em coordenadas do documento (pixels da
folha), em que `r` é o raio da linha naquele ponto. O traço é imutável: a borracha e a
re-suavização criam traços novos. O **desfazer** guarda listas de traços (e o tamanho da
folha), então cada passo custa só uma cópia rasa da lista.

Na tela e na exportação, o traço vira um **contorno**: um polígono por trecho entre cantos,
com pontas redondas, todos com a mesma orientação e preenchidos com a regra *nonzero*.
Assim os trechos e as junções se unem sem buracos (`geometry.outline`).

## O caminho de um traço

```
caneta ──► Canvas.pen_press/move/release ◄── (Windows Ink: tabletEvent | WinTab: wintab.py | mouse)
             │
             ├─ ao vivo (coordenadas de tela)
             │    filtro 1€ ──► corda puxada ──► pontos do traço (o que aparece)
             │    posição crua da caneta ──► raw_pts (usados para reconhecer formas)
             │    caneta parada por hold_ms ──► shapes.detect_shape(raw_pts)
             │                                    └─ reconheceu: o traço vira a forma, cuja ponta segue a caneta
             │
             └─ ao soltar (Canvas._process_free)
                  geometry.process_free:
                    reamostra ──► acha cantos vivos ──► alisa cada trecho (gaussiana)
                    ──► ajusta curvas Bézier (curvefit) ──► reamostra as curvas
                  fechar falhas (emenda as pontas em linhas próximas)
                  pontas finas (exceto nas pontas emendadas)
                  ──► Document.add_stroke ──► cache da tela
```

Todas as tolerâncias que a pessoa ajusta (corda, suavidade, distância para emendar, tempo
parado) são medidas em **pixels de tela**: o efeito é o mesmo em qualquer zoom.

O último traço à mão livre guarda os pontos de antes do processamento
(`Canvas._last_free`). Assim, mexer em *Suavidade*, *Pontas finas*, *Fechar falhas* ou
*Preservar cantos* refaz esse traço na hora (`Canvas.resmooth_last`).

## Algoritmos

### Estabilização ao vivo
1. **Filtro 1€** (Casiez, Roussel e Vogel, CHI 2012): passa-baixa cuja frequência de corte
   sobe com a velocidade. Devagar, alisa muito; rápido, quase não atrasa. O controle
   *Estabilização* (0–100) leva o corte mínimo de 10 Hz a 1,5 Hz (`filters.for_strength`).
2. **Corda puxada** ("lazy brush"): a ponta do traço só anda quando a caneta passa do
   comprimento da corda (0,6 px de tela por nível de estabilização), filtrando tremores
   menores que ela. A linha vermelha na tela mostra a corda.

### Alisamento ao soltar (`geometry.process_free`)
- **Cantos vivos**: ângulo entre os vizinhos a *k* amostras (janela de cerca de 10 px de
  tela); um máximo local acima de 65° é canto. Cada trecho entre cantos é alisado separado,
  então as quinas não arredondam.
- **Gaussiana com reflexão pontual** nas pontas (o índice −k vira 2·p₀ − pₖ): o primeiro e
  o último ponto ficam no lugar, e as pontas são alisadas tanto quanto o meio. O raio usa o
  dobro do sigma, para uniformizar a espessura.
- **Curvas Bézier** (Schneider, *Graphics Gems*, 1990): mínimos quadrados com
  reparametrização de Newton–Raphson, dividindo no ponto de maior erro. A tolerância cresce
  com a suavidade e tira as ondulações residuais.

### Reconhecimento de formas (`shapes.detect_shape`)
É feito sobre a **posição crua da caneta**, não sobre o traço estabilizado, porque a corda
arredonda as quinas. O traço é **fechado** quando as pontas ficam perto (até 20% da
diagonal) e o comprimento passa de 1,8 diagonal.

- **Abertos**: *arco* (ajuste de círculo de Bullock) só quando curva 40°+ e se ajusta bem
  melhor que uma reta; senão *reta* (desvio até 10% do comprimento: retas feitas à mão têm
  "barriga"); senão *linha quebrada*.
- **Fechados**: compara *círculo*, *elipse* (ajuste direto de Fitzgibbon, versão estável de
  Halír e Flusser; a elipse paga 25% de penalidade, para preferir o círculo, que é mais
  simples) e *polígono*. O polígono só ganha se tiver erro menor que 60% do da melhor forma
  redonda.
- **Polígonos**: Douglas–Peucker (tolerância de 5% da diagonal) → junta trechos que viram
  menos de 30° → reta por PCA em cada lado (ignorando 12% perto das quinas) → vértices na
  interseção dos lados. Uma quina só conta se o traço cru passar perto dela; isso evita que
  uma curva em S vire linha quebrada.
- **Embelezamento**: lados a até 7° da horizontal ou vertical da **tela** (considerando o
  giro da folha) ficam exatos. Com 4 lados e ângulos entre 75° e 105°, vira retângulo; com
  lados até 12% diferentes, quadrado.

### Fechar falhas
Ao soltar, cada ponta do traço procura o ponto mais próximo de outro traço dentro de
*Distância para fechar falhas* (12 px de tela). Se já encosta, ou se o traço já cruzou a
outra linha perto da ponta, nada muda. Se não, é criada uma ponte reta até lá. Retas e
linhas quebradas têm as pontas movidas direto para o ponto encontrado. Um traço também fecha
sobre o próprio começo, o que fecha contornos.

## Entrada da mesa

- **Windows Ink**: `Canvas.tabletEvent`. O evento é sempre aceito, para o Qt não gerar
  eventos de mouse duplicados. O botão lateral da caneta move a folha.
- **WinTab** (`wintab.py`): abre um contexto de sistema com a resolução nativa da mesa, lê a
  fila com `WTPacketsGet` a cada 4 ms e converte para coordenadas da janela usando a área de
  tela que o driver mapeou (`lcSys*`) e `ClientToScreen`, o que funciona em monitores com DPI
  diferentes. Nesse modo, os eventos do Windows Ink e o mouse emulado pela caneta são
  ignorados.
- **Mouse**: funciona como caneta com pressão 1, para testes. Durante 0,3 s após qualquer
  evento da mesa, o mouse é ignorado.

## Desenho na tela

`Canvas` mantém um **cache** (`QImage`) com papel, esboço e traços na vista atual. Um traço
novo é desenhado só no cache. Durante zoom, giro e movimento, o cache antigo é desenhado
transformado e refeito 150 ms depois. O traço em andamento, a corda, o anel de "segurar",
o cursor e os avisos são desenhados por cima a cada quadro.

## Exportação

- **PNG**: `QImage` do tamanho da folha, fundo transparente, DPI gravado.
- **SVG**: cada traço vira um `<path>` com o contorno ajustado em curvas Bézier (tolerância
  de 0,15 px), preenchimento *nonzero*. O tamanho físico (polegadas) usa o DPI da folha, para
  o Krita encaixar o vetor sobre o PNG.

## Arquivo de projeto `.traco`

JSON compacto:

```json
{"format": "tracofirme", "version": 1, "width": 2480, "height": 3508, "dpi": 300,
 "sketch": "C:/caminho/esboco.png",
 "strokes": [{"color": "#000000", "pts": [[x, y, r], ...]}]}
```

## Log de diagnóstico

Desligado por padrão; só é ligado em *Ajuda → Mesa digitalizadora…* e vale até fechar o
programa. Fica em `%LOCALAPPDATA%\TracoFirme\logs\tracofirme-AAAAMMDD-HHMMSS.jsonl` (são
mantidos os 20 mais recentes). Cada linha é um evento com `t` (ms desde o início) e `k`
(tipo):

| `k` | Conteúdo |
|---|---|
| `session` | versões, monitores e DPI, modo da mesa |
| `ink_press/move/release/hover` | eventos do Windows Ink: posição, pressão, tipo de ponteiro, botões |
| `wt_move/hover`, `wintab_open` | pacotes WinTab crus e convertidos; parâmetros do contexto |
| `mouse_*` | eventos de mouse e se foram ignorados |
| `stroke_begin/end` | ajustes em uso, forma resultante, quanto tempo a caneta ficou parada |
| `hold_reset` | a contagem do "segurar" recomeçou (quanto a caneta andou) |
| `hold_fire` | resultado do reconhecimento e as medidas usadas |

Eventos de caneta pairando são limitados a 10 por segundo.

## Decisões e limites conhecidos

- **Contorno por trechos** em vez de união geométrica: é mais simples e exato o bastante.
  Em curvas mais fechadas que a espessura da linha, o contorno de um trecho pode se cruzar
  (a regra *nonzero* cobre a maioria dos casos).
- **Estabilização ao vivo arredonda quinas** com corda longa; por isso o reconhecimento de
  formas usa a posição crua da caneta. Para quinas à mão livre, use estabilização baixa.
- **WinTab** foi escrito seguindo a especificação, sem uma mesa com WinTab disponível
  durante o desenvolvimento; o log de diagnóstico existe para depurar isso em campo.
- **Preferências** ficam no registro (`HKCU\Software\TracoFirme`); os testes usam
  `TracoFirmeTeste` e limpam ao terminar.
