from main import main


def test_main_runs(capsys):
    main()
    assert "sga-wordnet" in capsys.readouterr().out
