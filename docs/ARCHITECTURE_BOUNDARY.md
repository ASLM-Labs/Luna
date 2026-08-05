# Faz 2 Mimari Sınırı

Faz 2, isteğin yapısal yorumlanmasını ve açık bağlam hazırlığını kanıtlar.

## Var

- Faz 1 çekirdek kontratları;
- deterministik intent resolver;
- TaskContractDraft ve TaskContractBuilder;
- ContextSource, ContextBudget ve ContextBundle;
- yan etkisiz ContextCollector;
- planning öncesi TaskPreparation;
- CLI intent görünürlüğü;
- Faz 2 test ve verifier kapısı.

## Yok

- gerçek model inference;
- dosya sistemi veya internetten otomatik context okuma;
- shell;
- araç dispatcher;
- workspace yazma;
- verifier;
- kalıcı checkpoint veya hafıza;
- subagent.

ContextCollector yalnız çağıran katmanın gerçekten sağladığı içerikle çalışır.
Bir dosya yolu verilmesi, dosyanın gözlemlendiği anlamına gelmez.
