# Contribuindo

## Ambiente

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m tracofirme
```

## Testes

```bat
.venv\Scripts\python -m pytest
```

- `tests/test_geometry.py`, `test_shapes.py`, `test_curvefit.py`: algoritmos puros, com
  traços sintéticos tremidos gerados em `tests/helpers.py`.
- `tests/test_app.py`: ponta a ponta. Abre a janela sem tela (`QT_QPA_PLATFORM=offscreen`),
  desenha chamando `Canvas.pen_press/move/release` como a caneta faria e confere o resultado
  e a exportação.

Os testes usam a organização `TracoFirmeTeste` no `QSettings` e não mexem nas preferências
reais.

## Convenções

- Código, comentários, interface e documentação em **português**.
- Lógica de geometria **sem Qt** (`geometry.py`, `shapes.py`, `curvefit.py`, `filters.py`),
  para poder ser testada isoladamente.
- Tolerâncias que a pessoa sente (corda, suavidade, distância para emendar) em **pixels de
  tela**; converta com `1 / zoom`.
- Mudança de comportamento do traço ou das formas → teste novo com um traço sintético que
  reproduz o caso.
- Interface pensada para quem não é técnico: rótulos em linguagem comum e uma frase curta
  explicando cada opção. Coisas raras vão em *Mais opções*.

## Depurando problemas de mesa

Peça à pessoa um log (*Ajuda → Mesa digitalizadora… → Gravar log de diagnóstico*). O
formato está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md#log-de-diagnóstico). Com os eventos
`ink_*`/`wt_*`, dá para reproduzir o traço exato chamando `Canvas.pen_*` num teste.
