
INSERT INTO sources(code,name,publisher,source_type,base_uri,jurisdiction,license,authority_level)
VALUES
('TED','Tenders Electronic Daily','Publications Office of the European Union','PROCUREMENT','https://api.ted.europa.eu','EU',NULL,'OFFICIAL'),
('GLEIF','Global LEI Index','Global Legal Entity Identifier Foundation','ENTITY_REGISTRY','https://api.gleif.org/api/v1','GLOBAL','GLEIF terms','AUTHORITATIVE'),
('EURLEX','EUR-Lex / Cellar','Publications Office of the European Union','LEGAL_DOCUMENTS','https://publications.europa.eu/resource/celex','EU',NULL,'OFFICIAL')
ON CONFLICT (code) DO UPDATE SET
  name=EXCLUDED.name,
  publisher=EXCLUDED.publisher,
  source_type=EXCLUDED.source_type,
  base_uri=EXCLUDED.base_uri,
  active=TRUE;
