# Histórico de versões

## Próxima versão

### Novidades
- **Tema claro e escuro** em *Exibir › Tema da interface* (Igual ao Windows, Claro ou
  Escuro). Só a interface muda de cor: a folha continua branca. A escolha fica salva.
- Requer PySide6 6.8 ou mais novo (o `run.bat` atualiza sozinho).

## 0.2.0

### Novidades
- **Reconhecimento de formas ao segurar a caneta**: além de reta, arco e círculo, agora
  elipse, triângulo, retângulo, quadrado, polígonos e linha quebrada. Lados quase
  horizontais ou verticais (em relação à tela, mesmo com a folha girada) ficam exatos.
- **Curvas Bézier** ao soltar a caneta (algoritmo de Schneider): linhas mais limpas e SVG
  mais leve, com nós editáveis no Krita.
- **Cantos vivos preservados**: a suavidade não arredonda quinas.
- **Fechar falhas entre linhas**: pontas que terminam perto de outra linha são emendadas,
  para o balde de tinta do Krita não vazar.
- **Pontas finas** e espessura mais uniforme.
- **Suavidade ajusta o último traço**: mexer no controle refaz o traço que acabou de ser
  feito.
- **Estabilização com filtro 1€**, que se adapta à velocidade: o controle único
  *Estabilização* (leve → forte) combina o filtro e a corda.
- **Interface nova**: barra de ferramentas com ícones, painel com explicações curtas,
  *Mais opções* recolhido, aviso na tela ao reconhecer uma forma, guia rápido na primeira
  abertura (F1), diálogo da mesa com medidor de pressão ao vivo e botões do sistema em
  português.
- **Limpar desenho** na barra de ferramentas.
- **Log de diagnóstico** da mesa, desligado por padrão.

### Correções
- "Segurar parado" mais tolerante a um leve deslize da mão (8 px).
- Retas feitas à mão com barriga de até cerca de 9% continuam retas.
- Uma reta muito tremida não é mais confundida com um arco de círculo enorme.

## 0.1.0

- Primeira versão: estabilizador de corda, alisamento ao soltar, endireitar reta, arco e
  círculo ao segurar, Shift para retas, borracha parcial ou do traço inteiro, desfazer e
  refazer, zoom, giro, esboço de fundo, tamanho da folha, exportação PNG + SVG para o
  Krita, Windows Ink e WinTab.
